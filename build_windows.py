"""Gera dist/ExtratoClaro-Windows-x64.zip (Windows x64, sem precisar de Python instalado).

Uso:
    python build_windows.py --scratch C:\\pasta\\temporaria            # build + smoke
    python build_windows.py --scratch C:\\pasta\\temporaria --so-smoke # só testa o zip pronto

venv de build isolado dentro de --scratch (uv se houver, senão venv+pip), versões
fixadas abaixo. Empacota launcher.py e o que ele importa (dash, store, fmt, inter_pdf,
b3_pdf, mp_sync, creds) + pypdf + LICENSE. Nunca .env, banco ou PDF: o zip é
conferido no fim e o build falha se aparecer algo assim.

O smoke extrai o zip, roda o .exe com banco sintético (EXTRATO_CLARO_TESTE=1: sem
navegador), confere HTTP, importa um PDF sintético e fecha o próprio processo.
"""
import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
ZIP = os.path.join(REPO, "dist", "ExtratoClaro-Windows-x64.zip")
NOME = "ExtratoClaro"
# resolvidos em 2026-10-05 com Python 3.12.10 (uv pip install pyinstaller pypdf)
PINS = [
    "altgraph==0.17.5",
    "packaging==26.3",
    "pefile==2024.8.26",
    "pyinstaller==6.22.3",
    "pyinstaller-hooks-contrib==2026.8",
    "pypdf==6.19.0",
    "pywin32-ctypes==0.2.3",
    "setuptools==84.0.0",
]
# o que o dashboard usa; o resto do repo (CLIs, testes) não entra
MODULOS = ["launcher", "dash", "store", "fmt", "inter_pdf", "b3_pdf", "mp_sync", "creds", "pypdf"]
FORA = ["test_fin", "test_launcher", "build_windows", "cat", "inter_import", "b3_posicao"]
PROIBIDO = re.compile(r"(^|/)(\.env[^/]*|[^/]*\.(db|sqlite3?|pdf|spec)|\.git/.*)$", re.I)

LEIA_ME = """\
EXTRATO CLARO
Seu extrato do banco organizado, direto no seu computador.

COMO ABRIR
1. Clique com o botão direito em "ExtratoClaro-Windows-x64.zip" e escolha
   "Extrair tudo...". Depois clique em "Extrair".
   Importante: não abra o programa de dentro do .zip; extraia primeiro.
2. Abra a pasta "ExtratoClaro" que apareceu e dê dois cliques em
   "ExtratoClaro.exe".
3. Se o Windows mostrar "O Windows protegeu o computador", clique em
   "Mais informações" e depois em "Executar assim mesmo".
4. O painel abre sozinho no seu navegador. Uma janelinha "Extrato Claro"
   fica aberta enquanto o programa estiver em uso:
   - fechou a aba sem querer? Clique em "Abrir painel";
   - terminou? Clique em "Fechar o aplicativo".

COMO USAR
- Importar: no painel, clique em "Importar PDF / sincronizar Mercado Pago",
  escolha o PDF do extrato ou da fatura do cartão do Banco Inter e clique
  em "Importar". Importar o mesmo arquivo de novo não duplica nada.
- Organizar: a parte "Triar" mostra o que ficou sem categoria. Escreva uma
  categoria ao lado e ela passa a valer para os próximos lançamentos parecidos.
- A sincronização com o Mercado Pago não vem configurada nesta versão. O resto
  funciona sem ela.

SEUS DADOS
- Ficam só neste computador. Nada é enviado para a internet e o painel só
  abre aqui mesmo.
- Ficam guardados em:  %LOCALAPPDATA%\\3R Studios\\Extrato Claro
  (cole esse endereço na barra do Explorador de Arquivos e tecle Enter).
  O arquivo "fin.db" tem seus lançamentos. Para fazer cópia de segurança,
  feche o programa e copie esse arquivo.
- Apagar ou trocar a pasta do programa não apaga seus dados.

SE ALGO DER ERRADO
- Feche todas as janelas do Extrato Claro e abra de novo.
- Se a mensagem continuar, o arquivo "extrato-claro.log", na mesma pasta dos
  seus dados, explica o que aconteceu. Ele registra só o funcionamento do
  programa, mas dê uma olhada antes de enviar para alguém.

Requer Windows 10 ou 11 de 64 bits. Não precisa instalar nada.
"""


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def venv(scratch, uv):
    pasta = os.path.join(scratch, "build-venv")
    py = os.path.join(pasta, "Scripts", "python.exe")
    env = {**os.environ, "UV_CACHE_DIR": os.path.join(scratch, "uv-cache"),
           "PIP_CACHE_DIR": os.path.join(scratch, "pip-cache")}
    if not os.path.exists(py):
        if uv:
            run([uv, "venv", "--python", sys.executable, pasta], env=env)
        else:
            run([sys.executable, "-m", "venv", pasta])
    if uv:
        run([uv, "pip", "install", "--python", py, *PINS], env=env)
    else:
        run([py, "-m", "pip", "install", "-q", *PINS], env=env)
    # pins conferidos no que ficou instalado de fato
    run([py, "-c", "import importlib.metadata as m, sys\n"
         f"for p in {PINS!r}:\n"
         "    n, v = p.split('==')\n"
         "    assert m.version(n) == v, (n, m.version(n), v)\n"
         "print('pins ok', sys.version.split()[0])"])
    return py


def empacota(scratch, py):
    pyi = os.path.join(scratch, "pyinstaller")
    shutil.rmtree(pyi, ignore_errors=True)
    run([py, "-m", "PyInstaller", os.path.join(REPO, "launcher.py"),
         "--name", NOME, "--windowed", "--onedir", "--noconfirm", "--clean",
         "--noupx", "--paths", REPO, "--hidden-import", "pypdf",
         *[a for m in FORA for a in ("--exclude-module", m)],
         "--distpath", os.path.join(pyi, "dist"), "--workpath", os.path.join(pyi, "work"),
         "--specpath", os.path.join(pyi, "spec")],
        cwd=scratch, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    app = os.path.join(pyi, "dist", NOME)
    with open(os.path.join(app, "LEIA-ME.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(LEIA_ME)
    shutil.copyfile(os.path.join(REPO, "LICENSE"), os.path.join(app, "LICENSE.txt"))
    confere_modulos(py, os.path.join(app, f"{NOME}.exe"))
    return app


def confere_modulos(py, exe):
    out = subprocess.run([py, "-m", "PyInstaller.utils.cliutils.archive_viewer", "-l", "-r", exe],
                         capture_output=True, text=True, check=True).stdout
    nomes = set(re.findall(r"\b([A-Za-z_][\w.]*)\b", out))
    falta = [m for m in MODULOS if m not in nomes]
    sobra = [m for m in FORA if m in nomes]
    if falta or sobra:
        sys.exit(f"bundle errado: falta {falta}, sobra {sobra}")
    print("módulos ok:", ", ".join(MODULOS))


def zipa(app):
    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for raiz, dirs, arqs in os.walk(app):
            dirs.sort()
            for a in sorted(arqs):
                p = os.path.join(raiz, a)
                z.write(p, os.path.join(NOME, os.path.relpath(p, app)).replace(os.sep, "/"))
    confere_zip()


def confere_zip():
    with zipfile.ZipFile(ZIP) as z:
        nomes = z.namelist()
        ruins = [n for n in nomes if PROIBIDO.search(n)]
        # token do Mercado Pago começa assim; não pode haver nenhum no pacote
        com_token = [n for n in nomes if b"APP_USR-" in z.read(n)]
    if ruins or com_token:
        os.remove(ZIP)
        sys.exit(f"zip recusado: arquivos proibidos {ruins}, possível token {com_token}")
    for n in (f"{NOME}/{NOME}.exe", f"{NOME}/LEIA-ME.txt", f"{NOME}/LICENSE.txt"):
        assert n in nomes, n
    print(f"zip ok: {len(nomes)} arquivos, {os.path.getsize(ZIP)} bytes, sem .env/.db/.pdf")


# ---------------------------------------------------------------- smoke

def pdf_sintetico(linhas):
    """PDF de 1 página com texto puro, no layout do extrato do Inter."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    ops = ["BT /F1 10 Tf 14 TL 40 800 Td"] + [f"({esc(t)}) Tj T*" for t in linhas] + ["ET"]
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PDF = pdf_sintetico(["1 de Setembro de 2026 Saldo do dia: R$ 100,00",
                     'Pix enviado: "MERCADINHO PDF SMOKE" -R$ 7,50 R$ 92,50'])


def requisicao(porta, metodo, path="/", host=None, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=20)
    c.request(metodo, path, body=body,
              headers={"Host": host or f"127.0.0.1:{porta}", **(headers or {})})
    r = c.getresponse()
    corpo = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, r.getheader("Location"), corpo


def sobe(exe, env, arq_log, timeout=60):
    proc = subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe))
    fim = time.time() + timeout
    while time.time() < fim:
        if proc.poll() is not None:
            sys.exit(f"exe saiu cedo (código {proc.returncode}); log: {arq_log}")
        if os.path.exists(arq_log):
            with open(arq_log, encoding="utf-8") as f:
                m = re.search(r"pronto em http://127\.0\.0\.1:(\d+)/", f.read())
            if m:
                return proc, int(m[1])
        time.sleep(0.25)
    proc.kill()
    sys.exit("exe não ficou pronto a tempo")


def portas_escutando(pid):
    # Get-NetTCPConnection, não netstat: este traduz o estado ("ESCUTANDO") conforme o idioma
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          f"Get-NetTCPConnection -State Listen -OwningProcess {pid} | "
                          "ForEach-Object { '{0}:{1}' -f $_.LocalAddress, $_.LocalPort }"],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def fecha(proc, arq_log):
    """WM_CLOSE (taskkill sem /F) = mesmo caminho do X da janela. Só o nosso PID."""
    subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True)
        proc.wait(10)
        return False
    with open(arq_log, encoding="utf-8") as f:
        return proc.returncode == 0 and "encerrado" in f.read()


def smoke(scratch):
    base = os.path.join(scratch, "smoke", time.strftime("%Y%m%d-%H%M%S"))
    app_dir = os.path.join(base, "extraido")
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(app_dir)
    exe = os.path.join(app_dir, NOME, f"{NOME}.exe")
    antes = sorted(os.listdir(os.path.dirname(exe)))
    tmp = os.path.join(base, "tmp")
    os.makedirs(tmp)
    env = {k: v for k, v in os.environ.items()
           if k not in ("FIN_DB", "MP_ACCESS_TOKEN", "FIN_HOST", "FIN_PORT")}
    env.update(EXTRATO_CLARO_TESTE="1", TEMP=tmp, TMP=tmp, TMPDIR=tmp,
               LOCALAPPDATA=os.path.join(base, "localappdata"))
    res = {"exe": exe}

    # 1) FIN_DB sintético com uma linha conhecida
    db = os.path.join(base, "dados", "fin.db")
    os.makedirs(os.path.dirname(db))
    run([sys.executable, "-c",
         "import store\nwith store.conn() as c: store.upsert(c, [('smoke1','inter',"
         "'pix enviado','concluido',-42.0,'PADARIA SINTETICA SMOKE','2026-09-02')])"],
        cwd=REPO, env={**env, "FIN_DB": db})
    arq_log = os.path.join(base, "dados", "extrato-claro.log")
    proc, porta = sobe(exe, {**env, "FIN_DB": db}, arq_log)
    try:
        res["porta"] = porta
        res["escuta"] = portas_escutando(proc.pid)
        assert res["escuta"] and all(a.startswith("127.0.0.1:") for a in res["escuta"]), res
        st, _, pg = requisicao(porta, "GET")
        assert st == 200 and "<title>Extrato Claro</title>" in pg, st
        assert "PADARIA SINTETICA SMOKE" in pg, "linha sintética não apareceu"
        res["get"] = st
        res["host_estranho"] = requisicao(porta, "GET", host="malicioso.example")[0]
        assert res["host_estranho"] == 403
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        res["post_outro_site"] = requisicao(porta, "POST", "/regra", body="padrao=x&categoria=y",
                                            headers={**form, "Origin": "http://malicioso.example"})[0]
        assert res["post_outro_site"] == 403
        corpo = (b"--B\r\nContent-Disposition: form-data; name=\"pdf\"; filename=\"s.pdf\"\r\n"
                 b"Content-Type: application/pdf\r\n\r\n" + PDF + b"\r\n--B--\r\n")
        st, loc, _ = requisicao(porta, "POST", "/import", body=corpo, headers={
            "Content-Type": "multipart/form-data; boundary=B",
            "Origin": f"http://127.0.0.1:{porta}", "Referer": f"http://127.0.0.1:{porta}/"})
        res["import_pdf"] = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)["msg"][0]
        assert st == 303 and res["import_pdf"] == "importado -> s.pdf: 1", res["import_pdf"]
        assert "MERCADINHO PDF SMOKE" in requisicao(porta, "GET")[2]
    finally:
        res["fechou_limpo"] = fecha(proc, arq_log)
    res["exe_dir_inalterado"] = sorted(os.listdir(os.path.dirname(exe))) == antes

    # 2) sem FIN_DB: banco tem que ir para LOCALAPPDATA\3R Studios\Extrato Claro
    padrao = os.path.join(env["LOCALAPPDATA"], "3R Studios", "Extrato Claro")
    proc, porta = sobe(exe, env, os.path.join(padrao, "extrato-claro.log"))
    try:
        st, _, pg = requisicao(porta, "GET")
        assert st == 200 and "sem dados" in pg and "PADARIA" not in pg
        res["sem_fin_db"] = {"get": st, "db_criado": os.path.exists(os.path.join(padrao, "fin.db"))}
    finally:
        res["sem_fin_db"]["fechou_limpo"] = fecha(proc, os.path.join(padrao, "extrato-claro.log"))
    assert res["sem_fin_db"]["db_criado"]
    assert sorted(os.listdir(os.path.dirname(exe))) == antes
    print("smoke:", json.dumps(res, ensure_ascii=False, indent=1))
    assert res["fechou_limpo"] and res["sem_fin_db"]["fechou_limpo"], "não fechou pelo WM_CLOSE"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch", default=os.path.join(REPO, "build"),
                    help="pasta de trabalho (venv, PyInstaller, smoke)")
    ap.add_argument("--uv", default=os.environ.get("UV") or shutil.which("uv"))
    ap.add_argument("--so-smoke", action="store_true", help="não builda, só testa o zip")
    ap.add_argument("--sem-smoke", action="store_true")
    a = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("este build é só para Windows")
    scratch = os.path.abspath(a.scratch)
    os.makedirs(scratch, exist_ok=True)
    if not a.so_smoke:
        py = venv(scratch, a.uv)
        zipa(empacota(scratch, py))
    if not a.sem_smoke:
        smoke(scratch)
    print(f"{ZIP} ({os.path.getsize(ZIP)} bytes)")


if __name__ == "__main__":
    main()
