"""Importa PDF do Inter (extrato ou fatura do cartão) -> SQLite.

Uso: python inter_pdf.py arquivo.pdf [outro.pdf ...]

Único formato que o Inter ainda exporta é PDF. Texto vem do pypdf; o resto é regex.
ponytail: sem markitdown/pdfplumber. markitdown só embrulha extração de texto (a mesma
que pypdf dá) e arrasta um monte de dependência. Trocar só se o layout virar tabela real.
"""
import hashlib
import re
import sys
from collections import Counter

import store
from fmt import valor_br

MESES = {m: i for i, m in enumerate(
    "jan fev mar abr mai jun jul ago set out nov dez".split(), 1)}

# extrato: '19 de Julho de 2025' / fatura: '13 de jun. 2026' (sem o 2º 'de')
DIA = re.compile(r"(\d{1,2}) de ([A-Za-zçÇ]+)\.?(?: de)? (\d{4})")
# extrato: 'Pix recebido: "Cp :123-Rafael" R$ 0,10 R$ 8,75'  (valor, saldo)
# tipo é opcional: taxas vêm sem ':' ('Imposto IOF Adicional -R$ 3,44 -R$ 3,44')
EXTRATO = re.compile(r'^(?:(?P<tipo>[^:]+?): )?(?P<desc>.*?) ?(?P<val>-?R\$\s?[\d.,]+) '
                     r'(?P<saldo>-?R\$\s?[\d.,]+)$')
# fatura: '13 de jun. 2026 ZIG* *ZIGPAY - R$ 25,00'  ('+' = pagamento/estorno)
FATURA = re.compile(r"^\d{1,2} de [A-Za-zçÇ]+\.?(?: de)? \d{4} (?P<desc>.+?) "
                    r"(?P<sinal>\+ )?R\$\s?(?P<val>[\d.,]+)$")
CARTAO = re.compile(r"^CART[ÃA]O (\S+)")


def texto(path):
    """path ou file-like (o dash passa BytesIO do upload)."""
    try:
        import pypdf  # dep só aqui: quem importa CSV não precisa dela
    except ImportError:  # ponytail: instala na hora; zero setup pós-clone
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pypdf"], check=True)
        import pypdf
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(path).pages)


def data_iso(s):
    """'13 de jun. 2026' ou '19 de Julho de 2025' -> '2026-06-13'."""
    m = DIA.search(s)
    if not m:
        return None
    mes = MESES.get(m[2][:3].lower())
    return f"{m[3]}-{mes:02d}-{int(m[1]):02d}" if mes else None


def parse_extrato(txt):
    data, buf, out = None, "", []
    for linha in txt.splitlines():
        linha = linha.replace("\xa0", " ").replace(" ", " ").strip()
        if not linha:
            continue
        if "Saldo do dia" in linha:  # cabeçalho de dia (às vezes colado no texto anterior)
            data, buf = data_iso(linha), ""
            continue
        buf = f"{buf} {linha}" if buf else linha
        m = EXTRATO.match(buf)
        if not m:
            buf = buf if buf.count('"') == 1 else ""  # descrição quebrada em 2 linhas
            continue
        buf = ""
        valor = valor_br(m["val"])
        if data and valor:
            tipo = (m["tipo"] or "").strip().lower() or ("credito" if valor > 0 else "debito")
            out.append((tipo, m["desc"].strip(' "') or (m["tipo"] or "").strip(), valor, data))
    return out


def parse_fatura(txt):
    cartao, out = "", []
    for linha in txt.splitlines():
        linha = linha.replace("\xa0", " ").replace(" ", " ").strip()
        c = CARTAO.match(linha)
        if c:
            cartao = c[1]
            continue
        m = FATURA.match(linha)
        data = data_iso(linha) if m else None
        # ponytail: '+' é pagamento da fatura, que já aparece como saída no extrato.
        # Importar aqui contaria em dobro -> ignora.
        if not data or m["sinal"]:
            continue
        desc = m["desc"].strip().removesuffix(" -").strip()
        valor = valor_br(m["val"])
        if valor:
            out.append((f"cartao {cartao}".strip(), desc, -abs(valor), data))
    return out


def to_rows(itens):
    """ID determinístico e estável: chave do lançamento + nº da repetição no arquivo."""
    vistos, rows = Counter(), []
    for tipo, desc, valor, data in itens:
        chave = f"{data}|{tipo}|{desc}|{valor:.2f}"
        vistos[chave] += 1
        rid = "inter_" + hashlib.sha256(f"{chave}|{vistos[chave]}".encode()).hexdigest()[:16]
        rows.append((rid, "inter", tipo, "concluido", valor, desc, data))
    return rows


def parse(path):
    txt = texto(path)
    itens = parse_fatura(txt) if "Despesas da fatura" in txt else parse_extrato(txt)
    if not itens:
        # ValueError, não sys.exit: o dash chama isso dentro do handler HTTP
        raise ValueError("nenhuma movimentação encontrada (layout mudou?)")
    return to_rows(itens)


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python inter_pdf.py arquivo.pdf [...]")
    with store.conn() as c:
        for path in sys.argv[1:]:
            try:
                rows = parse(path)
            except ValueError as e:
                sys.exit(f"{path}: {e}")
            print(f"{path}: {store.upsert(c, rows)} movimentações -> {store.DB}")


if __name__ == "__main__":
    main()
