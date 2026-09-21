"""Extrato de POSIÇÃO da B3 (investidor.b3.com.br) -> tabela `posicao`.

Diferente de b3_pdf.py, que lê o extrato de MOVIMENTAÇÃO (fluxo: provento,
liquidação, subscrição). Movimentação não fecha posição: 'Transferência -
Liquidação' é o mesmo lançamento para compra e venda, sempre positivo, então
reconstruir carteira a partir dela chuta. O extrato de posição é o saldo
auditado pela B3 — é a verdade.

Uso: python b3_posicao.py posicao-*.pdf

Tabela `posicao` guarda um SNAPSHOT por data (PK data+produto), então importar o
mesmo PDF duas vezes é idempotente e o histórico de snapshots fica preservado.
"""
import re
import sys

import store
from inter_pdf import texto

# tudo numa linha só: o pypdf quebra as colunas do PDF da B3 em N linhas
SPACE = re.compile(r"\s+")

# FII / Fundo: 'BTLG11 - BTG PACTUAL ... Cotas INTER DISTRIBUIDORA ... 63 R$ 99,00 R$ 6.237,00'
RE_TICKER = re.compile(
    r"\b(?P<ticker>[A-Z]{4}\d{1,2}) - (?P<produto>.+?) "
    r"(?P<tipo>Cotas|Direito|Fundo) (?P<inst>[A-Z][A-Za-z ]+?) "
    r"(?P<qtd>\d[\d.]*) R\$ ?(?P<preco>[\d.,]+) R\$ ?(?P<valor>[\d.,]+)")

# Tesouro Direto: 'Tesouro IPCA+ 2029 BANCO SOFISA S/A 15/05/2029 0,17 R$ 540,95 R$ 655,26'
# '(?!Produto)' impede que o cabecalho da secao ('Tesouro Direto Produto
# Instituicao Vencimento...') seja engolido como nome do titulo.
RE_TESOURO = re.compile(
    r"(?P<produto>Tesouro (?:(?!Produto)[^|])+?) (?P<inst>BANCO [A-Z/ .]+?|INTER "
    r"DISTRIBUIDORA[A-Za-z ]+?) (?P<venc>\d{2}/\d{2}/\d{4}) (?P<qtd>[\d.,]+) "
    r"R\$ ?(?P<aplicado>[\d.,]+) R\$ ?(?P<valor>[\d.,]+)")

# CDB / CRA / LCI...: 'CDB - BANCO SOFISA S/A BANCO SOFISA S/A 10/12/2027 8736 R$ 1,29 R$ 11.253,19'
RE_RF = re.compile(
    r"(?P<produto>(?:CDB|CRA|CRI|LCI|LCA|LC|DEB) - (?:(?!Produto).)+?) "
    r"(?P<inst>BANCO [A-Z/ .]+?|INTER DISTRIBUIDORA[A-Za-z ]+?) "
    r"(?P<venc>\d{2}/\d{2}/\d{4}) (?P<qtd>\d[\d.]*) "
    r"R\$ ?(?P<preco>[\d.,]+) R\$ ?(?P<valor>[\d.,]+)")

DATA = re.compile(r"Data: (\d{2})/(\d{2})/(\d{4})")
CLASSE = {"CDB": "renda fixa", "CRA": "renda fixa", "CRI": "renda fixa",
          "LCI": "renda fixa", "LCA": "renda fixa", "LC": "renda fixa",
          "DEB": "renda fixa"}


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def parse(path):
    t = SPACE.sub(" ", texto(path))
    m = DATA.search(t)
    if not m:
        raise SystemExit("nao achei a data do extrato em %s" % path)
    data = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))

    rows = []
    for x in RE_TICKER.finditer(t):
        tk, tipo = x.group("ticker"), x.group("tipo")
        # acao/unit nao termina em 11/12/13 (CMIG4, VALE3); fundo listado sim
        classe = ("fiagro" if tipo == "Fundo"
                  else "fii" if re.match(r"^[A-Z]{4}1[0-9]$", tk) else "acao")
        rows.append(dict(
            data=data, classe=classe, inst=x.group("inst").strip()[:24],
            ticker=tk, produto="%s - %s" % (tk, x.group("produto").strip()),
            tipo=tipo, venc=None, qtd=num(x.group("qtd")),
            preco=num(x.group("preco")), valor=num(x.group("valor"))))
    for x in RE_TESOURO.finditer(t):
        rows.append(dict(
            data=data, classe="tesouro", ticker="",
            inst=x.group("inst").strip()[:24],
            produto=x.group("produto").strip(), tipo="Título",
            venc=x.group("venc"), qtd=num(x.group("qtd")),
            preco=None, valor=num(x.group("valor"))))
    for x in RE_RF.finditer(t):
        p = x.group("produto").strip()
        rows.append(dict(
            data=data, classe=CLASSE.get(p.split(" -")[0], "renda fixa"),
            ticker="", inst=x.group("inst").strip()[:24],
            produto=p, tipo="Título", venc=x.group("venc"),
            qtd=num(x.group("qtd")), preco=num(x.group("preco")),
            valor=num(x.group("valor"))))
    return data, rows


def main(paths):
    c = store.conn()
    # PK inclui instituicao e vencimento: o mesmo 'Tesouro IPCA+ 2029' aparece
    # duas vezes no extrato (custodiado no Sofisa e no Inter) e sao posicoes
    # distintas — sem isso uma sobrescreve a outra.
    # migracao sem perda: se existe uma `posicao` de schema antigo, ela e
    # RENOMEADA (nunca dropada) e a nova e recriada — o snapshot e reimportavel
    # a partir dos PDFs, mas apagar dado do usuario nao e decisao do script.
    cols = [r[1] for r in c.execute("PRAGMA table_info(posicao)")]
    if cols and "inst" not in cols:
        n = 1
        while c.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                        ("posicao_v%d" % n,)).fetchone():
            n += 1
        c.execute("ALTER TABLE posicao RENAME TO posicao_v%d" % n)
        print("schema antigo preservado em posicao_v%d" % n)
    c.execute("""CREATE TABLE IF NOT EXISTS posicao (
        data TEXT NOT NULL, classe TEXT NOT NULL, ticker TEXT NOT NULL DEFAULT '',
        produto TEXT NOT NULL, inst TEXT NOT NULL DEFAULT '', tipo TEXT,
        venc TEXT, qtd REAL, preco REAL, valor REAL NOT NULL,
        PRIMARY KEY (data, produto, inst, venc))""")
    for p in paths:
        data, rows = parse(p)
        c.executemany(
            "INSERT OR REPLACE INTO posicao (data,classe,ticker,produto,inst,tipo,"
            "venc,qtd,preco,valor) VALUES (:data,:classe,:ticker,:produto,:inst,"
            ":tipo,:venc,:qtd,:preco,:valor)", rows)
        c.commit()
        tot = sum(r["valor"] for r in rows)
        print("%s: %s -> %d posicoes, R$ %.2f" % (p.split("\\")[-1], data, len(rows), tot))
        for r in sorted(rows, key=lambda r: (r["classe"], -r["valor"])):
            print("   %-8s %-9s %10.2f  %s" % (
                r["classe"], r["ticker"] or "-", r["valor"], r["produto"][:56]))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1:]))
