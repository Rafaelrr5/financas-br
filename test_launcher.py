"""Testes do launcher do Extrato Claro. python test_launcher.py

Tudo em pasta temporária: não abre navegador, não cria janela, não toca no banco real.
"""
import http.client
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="extrato_claro_test_")
os.environ["FIN_DB"] = os.path.join(TMP, "dados", "fin.db")  # antes de qualquer import de store
os.environ["EXTRATO_CLARO_TESTE"] = "1"

import launcher  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


class Caminhos(unittest.TestCase):
    def test_padrao_em_localappdata(self):
        env = {"LOCALAPPDATA": r"C:\Users\x\AppData\Local", "FIN_DB": r"C:\outro\fin.db"}
        self.assertEqual(launcher.caminho_db(env),
                         os.path.join(r"C:\Users\x\AppData\Local", "3R Studios",
                                      "Extrato Claro", "fin.db"))

    def test_fin_db_so_em_teste(self):
        env = {"LOCALAPPDATA": TMP, "FIN_DB": os.path.join(TMP, "x.db"),
               "EXTRATO_CLARO_TESTE": "1"}
        self.assertEqual(launcher.caminho_db(env), os.path.join(TMP, "x.db"))

    def test_sem_localappdata(self):
        self.assertTrue(launcher.pasta_dados({}).endswith(
            os.path.join("AppData", "Local", "3R Studios", "Extrato Claro")))

    def test_banco_nunca_ao_lado_do_exe(self):
        exe_dir = os.path.dirname(sys.executable)
        self.assertNotEqual(os.path.dirname(launcher.caminho_db({"LOCALAPPDATA": TMP})),
                            exe_dir)


class Inicio(unittest.TestCase):
    def test_importar_launcher_nao_carrega_banco(self):
        # store lê FIN_DB na importação: o launcher tem que definir o caminho antes
        out = subprocess.run([sys.executable, "-c",
                              "import sys, launcher; print('store' in sys.modules)"],
                             cwd=AQUI, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")

    def test_prepara_cria_banco_e_log_na_pasta_de_teste(self):
        dash, db, arq_log = launcher.prepara()
        import store
        self.assertEqual(db, os.environ["FIN_DB"])
        self.assertEqual(store.DB, db)
        self.assertTrue(os.path.exists(db))
        self.assertEqual(os.path.dirname(arq_log), os.path.dirname(db))
        self.assertTrue(hasattr(dash, "H"))

    def test_erros_amigaveis(self):
        import sqlite3
        self.assertIn("permissão", launcher.explica(PermissionError()))
        self.assertIn("arquivo de dados", launcher.explica(sqlite3.OperationalError("locked")))
        self.assertIn("painel local", launcher.explica(OSError()))
        self.assertIn("deu errado", launcher.explica(KeyError()))

    def test_pasta_sem_permissao_vira_mensagem(self):
        with mock.patch("os.makedirs", side_effect=PermissionError("negado")), \
                mock.patch.object(launcher, "avisa_erro") as aviso:
            self.assertEqual(launcher.main(), 1)
        self.assertIn("Sem permissão", aviso.call_args[0][0])

    def test_tkinter_disponivel(self):
        import tkinter
        self.assertGreaterEqual(tkinter.TkVersion, 8.6)


class PdfCongelado(unittest.TestCase):
    def test_exe_sem_pypdf_nao_instala_e_explica(self):
        import inter_pdf
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(sys.modules, {"pypdf": None}), \
                mock.patch("subprocess.run", side_effect=AssertionError("pip chamado")):
            with self.assertRaises(RuntimeError) as cm:
                inter_pdf.texto("qualquer.pdf")
        self.assertIn("Baixe o .zip de novo", str(cm.exception))


class Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dash, _, _ = launcher.prepara()
        cls.srv = launcher.cria_servidor(cls.dash)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        launcher.espera_pronto(cls.srv)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def pede(self, metodo, host=None, headers=None, body=None):
        c = http.client.HTTPConnection(launcher.HOST, self.srv.server_port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.srv.server_port}", **(headers or {})}
        c.request(metodo, "/" if metodo == "GET" else "/regra", body=body, headers=h)
        r = c.getresponse()
        r.read()
        c.close()
        return r

    def test_so_loopback_e_porta_do_sistema(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")
        self.assertNotIn(self.srv.server_port, (0, 8000))
        self.assertEqual(launcher.url(self.srv), f"http://127.0.0.1:{self.srv.server_port}/")

    def test_porta_ocupada_nao_e_tomada(self):
        outro = socket.socket()
        outro.bind(("127.0.0.1", 0))
        outro.listen()
        porta = outro.getsockname()[1]
        try:
            with self.assertRaises(OSError):
                launcher.cria_servidor(self.dash, porta)
            novo = launcher.cria_servidor(self.dash)
            self.assertNotEqual(novo.server_port, porta)
            novo.server_close()
            socket.create_connection(("127.0.0.1", porta), timeout=5).close()  # dono intacto
        finally:
            outro.close()

    def test_pagina_responde(self):
        self.assertEqual(self.pede("GET").status, 200)
        self.assertEqual(self.pede("GET", host=f"localhost:{self.srv.server_port}").status, 200)

    def test_host_estranho_bloqueado(self):  # DNS rebinding
        self.assertEqual(self.pede("GET", host="malicioso.example").status, 403)

    def test_post_de_outro_site_bloqueado(self):
        corpo = "padrao=zzteste&categoria=lazer"
        tipo = {"Content-Type": "application/x-www-form-urlencoded"}
        r = self.pede("POST", headers={**tipo, "Origin": "http://malicioso.example"}, body=corpo)
        self.assertEqual(r.status, 403)
        r = self.pede("POST", headers={**tipo, "Origin": f"http://127.0.0.1:{self.srv.server_port}"},
                      body=corpo)
        self.assertEqual(r.status, 303)

    def test_erro_de_request_vai_para_o_log(self):
        with self.assertLogs("extrato_claro", "ERROR"):
            try:
                raise ValueError("boom")
            except ValueError:
                self.srv.handle_error(None, ("127.0.0.1", 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
