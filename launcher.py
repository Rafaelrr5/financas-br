"""Extrato Claro: abre o dashboard com dois cliques. python launcher.py (ou ExtratoClaro.exe)

O que faz, na ordem:
1. banco em %LOCALAPPDATA%\\3R Studios\\Extrato Claro\\fin.db — nunca ao lado do .exe,
   que pode estar numa pasta só-leitura ou ser apagado junto com o zip;
2. sobe o mesmo dash.H do `python dash.py`, só que em 127.0.0.1 numa porta livre que o
   sistema escolhe (não toma a 8000 de outro programa);
3. confere que a página responde de verdade e só então abre o navegador;
4. mostra uma janelinha com "Abrir painel" e "Fechar" — fechar o navegador não deixa
   um servidor órfão rodando sem jeito de parar.

EXTRATO_CLARO_TESTE=1: não abre navegador e respeita FIN_DB (só para teste automatizado).
"""
import logging
import logging.handlers
import os
import re
import socket
import socketserver
import sys
import threading
import traceback
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer

NOME = "Extrato Claro"
HOST = "127.0.0.1"  # fixo: o dashboard não tem login, o isolamento é o loopback
log = logging.getLogger("extrato_claro")
PRONTO = re.compile(r"pronto em http://127\.0\.0\.1:(\d+)/")  # testes acham a porta no log
# proxy do sistema não pode interceptar a conversa com o próprio loopback
SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def modo_teste(env=os.environ):
    return env.get("EXTRATO_CLARO_TESTE") == "1"


def pasta_dados(env=os.environ):
    base = env.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "3R Studios", NOME)


def caminho_db(env=os.environ):
    """FIN_DB solto no ambiente do usuário não deve mudar onde o app grava; só em teste."""
    if modo_teste(env) and env.get("FIN_DB"):
        return os.path.abspath(env["FIN_DB"])
    return os.path.join(pasta_dados(env), "fin.db")


def configura_log(pasta):
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "extrato-claro.log")
    for velho in log.handlers[:]:  # prepara() de novo (testes) não duplica linhas
        log.removeHandler(velho)
        velho.close()
    h = logging.handlers.RotatingFileHandler(arq, maxBytes=1_000_000, backupCount=1,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    # .exe sem console: stdout/stderr são None e traceback de request sumiria
    if sys.stdout is None or sys.stderr is None:
        fluxo = open(arq, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or fluxo
        sys.stderr = sys.stderr or fluxo
    return arq


def handler(dash):
    class Handler(dash.H):
        timeout = 30  # socket de preconnect do navegador não prende uma thread para sempre

        def permitido(self):
            # Host fixo barra DNS rebinding; Origin barra POST vindo de outro site
            if self.headers.get("Host") not in self.server.hosts:
                return False
            origem = self.headers.get("Origin")
            return origem is None or origem in self.server.origens

        def do_GET(self):
            if not self.permitido():
                return self.send_error(403)
            super().do_GET()

        def do_POST(self):
            if not self.permitido():
                return self.send_error(403)
            super().do_POST()

    return Handler


class Servidor(ThreadingHTTPServer):
    allow_reuse_address = False  # no Windows, SO_REUSEADDR deixaria dividir porta alheia
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # TCPServer, não HTTPServer: este faz getfqdn(), que trava segundos em certas redes
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]
        p = self.server_port
        self.hosts = {f"{HOST}:{p}", f"localhost:{p}"}
        self.origens = {f"http://{h}" for h in self.hosts}

    def handle_error(self, request, client_address):
        log.error("erro atendendo %s\n%s", client_address, traceback.format_exc())


def cria_servidor(dash, porta=0):
    """porta 0 = o sistema escolhe uma livre. Nunca escuta fora do loopback."""
    return Servidor((HOST, porta), handler(dash))


def url(srv):
    return f"http://{HOST}:{srv.server_port}/"


def espera_pronto(srv, tentativas=50):
    """GET / de verdade (roda as queries no banco), não só 'a porta abriu'."""
    erro = None
    for _ in range(tentativas):
        try:
            with SEM_PROXY.open(url(srv), timeout=10) as r:
                if r.status == 200 and NOME.encode() in r.read():
                    return
                erro = RuntimeError(f"resposta inesperada: HTTP {r.status}")
        except Exception as e:  # noqa: BLE001 — qualquer falha vira mensagem amigável
            erro = e
        threading.Event().wait(0.2)
    raise RuntimeError(f"o painel não respondeu ({erro})")


def prepara(env=os.environ):
    """Pastas, log e banco. Devolve (dash, caminho do db, caminho do log)."""
    db = caminho_db(env)
    arq_log = configura_log(os.path.dirname(db) if modo_teste(env) else pasta_dados(env))
    os.makedirs(os.path.dirname(db), exist_ok=True)
    os.environ["FIN_DB"] = db  # antes do import: store.DB é lido na importação
    import dash
    import store
    store.DB = db
    with store.conn() as c:  # cria o schema já; banco corrompido/bloqueado falha aqui
        c.execute("SELECT 1 FROM movimentacoes LIMIT 1")
    return dash, db, arq_log


def explica(e):
    """Exceção -> frase para quem não programa."""
    if isinstance(e, PermissionError):
        return "Sem permissão para gravar na pasta de dados."
    if type(e).__name__ in ("OperationalError", "DatabaseError"):
        return ("Não foi possível abrir o arquivo de dados. Feche outras janelas do "
                "Extrato Claro e tente de novo.")
    if isinstance(e, OSError):
        return "O computador não deixou o Extrato Claro iniciar o painel local."
    return "Algo deu errado ao iniciar."


def avisa_erro(texto):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, NOME, 0x10)  # MB_ICONERROR
    else:
        print(texto, file=sys.stderr)


def janela(srv, abrir_navegador):
    import tkinter as tk

    root = tk.Tk()
    root.title(NOME)
    root.resizable(False, False)
    status = tk.StringVar(value="Abrindo o painel…")
    tk.Label(root, text=NOME, font=("Segoe UI", 14, "bold")).pack(padx=24, pady=(18, 4))
    tk.Label(root, textvariable=status, font=("Segoe UI", 10), wraplength=320,
             justify="center").pack(padx=24, pady=(0, 12))
    botoes = tk.Frame(root)
    botoes.pack(padx=24, pady=(0, 18))
    abrir = tk.Button(botoes, text="Abrir painel", width=16, state="disabled",
                      command=lambda: webbrowser.open(url(srv)))
    abrir.pack(side="left", padx=4)

    def fechar():
        status.set("Fechando…")
        root.update_idletasks()
        srv.shutdown()
        root.destroy()

    tk.Button(botoes, text="Fechar o aplicativo", width=16, command=fechar).pack(side="left",
                                                                                padx=4)
    root.protocol("WM_DELETE_WINDOW", fechar)  # X da janela também encerra o servidor

    def pronto():
        abrir.config(state="normal")
        status.set("O painel está aberto no navegador.\nSe fechar a aba, clique em "
                   "\"Abrir painel\". Para sair, clique em \"Fechar o aplicativo\".")
        if abrir_navegador:
            webbrowser.open(url(srv))

    def falhou(msg):
        avisa_erro(msg)
        fechar()

    def checa():
        try:
            espera_pronto(srv)
        except Exception as e:  # noqa: BLE001
            log.error("painel não ficou pronto: %s", e)
            msg = f"O painel não respondeu.{detalhes()}"
            root.after(0, falhou, msg)
            return
        log.info("pronto em %s", url(srv))
        root.after(0, pronto)

    threading.Thread(target=checa, daemon=True).start()
    root.mainloop()


def log_atual():
    for h in log.handlers:
        if isinstance(h, logging.FileHandler):
            return h.baseFilename
    return None


def detalhes():
    arq = log_atual()
    return f"\n\nDetalhes técnicos foram salvos em:\n{arq}" if arq else ""


def main():
    try:
        dash, db, _ = prepara()
        log.info("iniciando %s; banco em %s", NOME, db)
        srv = cria_servidor(dash)
    except Exception as e:  # noqa: BLE001
        log.error("falha ao iniciar\n%s", traceback.format_exc())
        avisa_erro(f"{explica(e)}{detalhes()}")
        return 1
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        janela(srv, abrir_navegador=not modo_teste())
    except Exception:  # noqa: BLE001 — ex.: tkinter ausente
        log.error("falha na janela\n%s", traceback.format_exc())
        avisa_erro(f"Não foi possível mostrar a janela do aplicativo.{detalhes()}")
        srv.shutdown()
        return 1
    srv.server_close()
    log.info("encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
