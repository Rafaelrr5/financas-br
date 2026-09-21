"""Extrato de Movimentação da B3 (investidor.b3.com.br) -> tabela b3_mov.

Complemento por ativo da seção de Investimentos: qual FII/ação pagou quanto.

ponytail: NÃO entra em `movimentacoes`. O lado caixa desses eventos já vem do extrato do
Inter ("* PROV * RENDIMENTO 63 BTLG11", "NOTA BOV"), então importar aqui contaria em dobro.
Tabela própria = zero risco de duplicar e zero migração no CHECK de `origem`.

Uso: python b3_pdf.py movimentacao-*.pdf
"""
import hashlib
import re
import sys
from collections import Counter

import store
from fmt import valor_br
from inter_pdf import MESES, texto

DIA = re.compile(r"^(\d{1,2}) de ([A-Za-zçÇ]+) de (\d{4})$")
# cabeçalho de coluna, rodapé e bloco de filtros: nada disso é lançamento
LIXO = re.compile(r"^(Movimentação Produto|Unitário$|Valor da$|Operação$|Extrato de Movimenta"
                  r"|acesse investidor|Filtros aplicados|Data Inicial|Tipo de |Instituição:)")
# âncora do registro: 'Quantidade R$ PreçoUnitário R$ ValorOperação' ('R$ -' quando não tem
# valor, ex. direito de subscrição). O texto do pypdf vem com as colunas embaralhadas e
# quebradas em várias linhas — só a cauda numérica é confiável para separar um registro do outro.
TAIL = re.compile(r"(?<![\d,.])(?P<qtd>\d[\d.]*(?:,\d+)?) R\$ ?(?P<preco>[\d.,]+|-)"
                  r" R\$ ?(?P<valor>[\d.,]+|-)")
TICKER = re.compile(r"\b([A-Z]{4}\d{1,2})\b")
# tipos de movimentação da B3. Ordenados por tamanho na regex: 'Transferência - Liquidação'
# tem que casar antes de 'Transferência'.
# ponytail: lista fixa. Tipo novo da B3 cai no fallback (mov = início do texto do registro,
# que fica guardado inteiro em `produto`) — não perde dado, só não agrupa bonito.
MOVS = ("Transferência - Liquidação", "Juros Sobre Capital Próprio",
        "Direitos de Subscrição - Não Exercido", "Direito de Subscrição",
        "Cessão de Direitos - Solicitada", "Cessão de Direitos", "Leilão de Fração",
        "Fração em Ativos", "Bonificação em Ativos", "Rendimento", "Dividendo", "Empréstimo",
        "Transferência", "Amortização", "Atualização", "Subscrição", "Vencimento", "Reembolso",
        "Grupamento", "Desdobro", "Resgate", "Estorno", "Compra", "Venda", "Juros", "Cisão")
LABEL = re.compile("(" + "|".join(re.escape(m) for m in sorted(MOVS, key=len, reverse=True))
                   + ")", re.I)
CANON = {m.lower(): m for m in MOVS}   # 'AMORTIZAÇÃO' no PDF -> 'Amortização' na tabela
# proventos: dinheiro que o ativo pagou. O resto (liquidação, empréstimo, subscrição) é
# posição ou negociação — somar junto misturaria compra de cota com renda recebida.
PROVENTOS = ("Rendimento", "Dividendo", "Juros Sobre Capital Próprio", "Amortização", "Juros")


def parse_texto(txt):
    """-> [(data, mov, ticker, produto, qtd, preco, valor)]. produto = registro cru."""
    linhas = []
    for linha in txt.splitlines():
        linha = linha.replace("\xa0", " ").strip()
        if not linha or LIXO.match(linha):
            continue
        m = DIA.match(linha)
        mes = MESES.get(m[2][:3].lower()) if m else None
        linhas.append(f"@{m[3]}-{mes:02d}-{int(m[1]):02d}@" if mes else linha)

    out, data = [], None
    for pedaco in re.split(r"@(\d{4}-\d{2}-\d{2})@", " ".join(linhas))[1:]:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pedaco):
            data = pedaco
            continue
        pos = 0
        for m in TAIL.finditer(pedaco):
            reg = re.sub(r"\s+", " ", pedaco[pos:m.start()]).strip()
            pos = m.end()
            lab = LABEL.match(reg)
            tk = TICKER.search(reg)
            out.append((data, CANON.get(lab[1].lower(), lab[1]) if lab else reg[:40],
                        tk[1] if tk else "", reg[:200],
                        valor_br(m["qtd"]) or 0.0, valor_br(m["preco"]) or 0.0,
                        valor_br(m["valor"]) or 0.0))
    return out


def to_rows(itens):
    """ID determinístico: chave do evento + nº da repetição no arquivo (mesmo esquema do Inter)."""
    vistos, rows = Counter(), []
    for data, mov, ticker, produto, qtd, preco, valor in itens:
        chave = f"{data}|{mov}|{ticker}|{qtd:.4f}|{valor:.2f}"
        vistos[chave] += 1
        rid = "b3_" + hashlib.sha256(f"{chave}|{vistos[chave]}".encode()).hexdigest()[:16]
        rows.append((rid, data, mov, ticker, produto, qtd, preco, valor))
    return rows


def parse(path):
    itens = parse_texto(texto(path))
    if not itens:
        # ValueError, não sys.exit: o dash chama isso dentro do handler HTTP
        raise ValueError("nenhum evento encontrado (é o extrato de movimentação da B3?)")
    return to_rows(itens)


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python b3_pdf.py movimentacao.pdf [...]")
    with store.conn() as c:
        for path in sys.argv[1:]:
            try:
                rows = parse(path)
            except ValueError as e:
                sys.exit(f"{path}: {e}")
            print(f"{path}: {store.upsert_b3(c, rows)} eventos -> {store.DB}")


if __name__ == "__main__":
    main()
