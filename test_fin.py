"""Check único: parser Inter, valores BR, idempotência do upsert. python test_fin.py"""
import os
import tempfile

os.environ["FIN_DB"] = os.path.join(tempfile.gettempdir(), "fin_test.db")
if os.path.exists(os.environ["FIN_DB"]):
    os.remove(os.environ["FIN_DB"])

import store  # noqa: E402
import inter_import as ii  # noqa: E402

# --- valores em formato brasileiro
assert ii.valor_br("R$ 1.234,56") == 1234.56
assert ii.valor_br("-1.234,56") == -1234.56
assert ii.valor_br("(1.234,56)") == -1234.56
assert ii.valor_br("R$ 0,99") == 0.99
assert ii.valor_br("") is None and ii.valor_br("-") is None
assert ii.data_br("01/08/2026") == "2026-08-01"
assert ii.data_br("Saldo total") is None

# --- CSV com metadados antes do cabeçalho, latin-1, separador ;
CSV = (
    "Extrato Conta Corrente\n"
    "Banco Inter S.A.\n"
    "Período: 01/07/2026 a 31/07/2026\n"
    "\n"
    "Data Lançamento;Histórico;Descrição;Valor;Saldo\n"
    "05/07/2026;PIX ENVIADO;Farmácia São João;-89,90;1.910,10\n"
    "06/07/2026;COMPRA DEBITO;Supermercado Pão de Açúcar;-1.234,56;675,54\n"
    "07/07/2026;PIX RECEBIDO;Salário;R$ 5.000,00;5.675,54\n"
    "Saldo final;;;;5.675,54\n"
)
path = os.path.join(tempfile.gettempdir(), "extrato_test.csv")
with open(path, "w", encoding="latin-1") as f:
    f.write(CSV)

rows = ii.parse(path)
assert len(rows) == 3, rows
assert [r[4] for r in rows] == [-89.90, -1234.56, 5000.00]
assert rows[0][6] == "2026-07-05"
assert store.categoriza(rows[0][5]) == "saude"
assert store.categoriza(rows[1][5]) == "mercado"
assert store.categoriza("coisa aleatoria") == "outros"
# categorização usa tipo + descrição (no extrato Inter o sentido está no tipo)
assert store.categoriza("debito b3 LIQUIDACAO B3 * 01/08/2025") == "aplicacao"
assert store.categoriza("credito evento b3 * PROV * RENDIMENTO 2 AFHI11") == "rendimento"
assert store.categoriza("debito online td Prot.86435378 IPCA+ 2029") == "aplicacao"
assert store.categoriza("pagamento efetuado Pagamento fatura cartao Inter") == "fatura"
assert store.categoriza("salario recebido - portabilidade 341 4980") == "salario"
assert store.categoriza("pix enviado Cp :10573521-Rafael") == "transferencia"
# 'ltda' não pode virar investimento por causa de 'td'
assert store.categoriza("cartao 5555 LeodrogasLtda") == "saude"

# --- upsert idempotente: reimportar não duplica
with store.conn() as c:
    store.upsert(c, rows)
    store.upsert(c, ii.parse(path))
    assert c.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0] == 3
    gasto = c.execute("SELECT SUM(-valor) FROM movimentacoes WHERE valor<0").fetchone()[0]
    assert round(gasto, 2) == 1324.46, gasto

# --- PDF do Inter: texto -> lançamentos (não abre PDF, testa só os parsers de texto)
import inter_pdf as ip  # noqa: E402

EXTRATO_TXT = (
    "Valor Saldo por transação19 de Julho de 2025 Saldo do dia: R$ 8,75\n"
    'Pix recebido: "Cp :10573521-Rafael" R$ 0,10 R$ 8,75\n'
    'Est Cred Digital Boleto: "Estorno boleto credito" -R$ 660,22 R$ 8,75\n'
    "1 de Agosto de 2025 Saldo do dia: R$ 503,49\n"
    "Imposto IOF Adicional -R$ 3,44 R$ 500,05\n"          # sem 'tipo:'
    'Credito B3 Btb: "* PROV * Tx. Emprest. PETR3\n'      # descrição quebrada em 2 linhas
    '2025" R$ 0,02 R$ 500,07\n'
    "Fale com a gente\n"
    "Saldo disponível:\n"
    "R$ 10.001,05\n"
)
ext = ip.parse_extrato(EXTRATO_TXT)
assert [x[2] for x in ext] == [0.10, -660.22, -3.44, 0.02], ext
assert [x[3] for x in ext] == ["2025-07-19", "2025-07-19", "2025-08-01", "2025-08-01"], ext
assert ext[2][0] == "debito" and ext[2][1] == "Imposto IOF Adicional", ext[2]
assert ext[3][1] == "* PROV * Tx. Emprest. PETR3 2025", ext[3]

FATURA_TXT = (
    "Despesas da fatura\n"
    "CARTÃO 5364****0848\n"
    "Data Movimentação Beneficiário Valor\n"
    "13 de jun. 2026 ZIG* *ZIGPAY - R$ 25,00\n"
    "16 de jun. 2026 Wellhub Rafael Rocha R - R$ 69,99\n"
    "23 de jun. 2026 PAGAMENTO ON LINE - + R$ 99,68\n"     # pagamento: ignorado
    "Total CARTÃO 5364****0848 R$ 94,99\n"
    "1 + 2 de R$ 667,65 R$ 2.002,95\n"                     # tabela de parcelamento: ignorada
)
fat = ip.parse_fatura(FATURA_TXT)
assert [x[2] for x in fat] == [-25.0, -69.99], fat
assert fat[0] == ("cartao 5364****0848", "ZIG* *ZIGPAY", -25.0, "2026-06-13"), fat[0]

# mesma compra 2x no mesmo dia = 2 lançamentos, mas IDs estáveis entre importações
dobrada = [("cartao 1", "PADARIA", -10.0, "2026-06-13")] * 2
assert len({r[0] for r in ip.to_rows(dobrada)}) == 2
assert [r[0] for r in ip.to_rows(dobrada)] == [r[0] for r in ip.to_rows(dobrada)]

# --- regras manuais: ganham das keywords, valem retroativo e nas próximas importações
with store.conn() as c:
    store.upsert(c, [("x1", "inter", "cartao 1", "concluido", -20.0, "PINGO NO I", "2026-06-01"),
                     ("x2", "inter", "cartao 1", "concluido", -9.0, "IFD*64610153", "2026-06-02")])
    cat = lambda i: c.execute("SELECT categoria FROM movimentacoes WHERE id=?", (i,)).fetchone()[0]
    assert (cat("x1"), cat("x2")) == ("outros", "alimentacao")

    assert store.add_regra(c, "Pingo no I", "lazer") == 1      # recategoriza retroativo
    assert cat("x1") == "lazer"
    assert store.add_regra(c, "ifd*", "delivery") == 1         # regra vence a keyword fixa
    assert cat("x2") == "delivery"
    assert store.add_regra(c, "pingo no i", "bar") == 1        # regravar padrão só troca a categoria
    assert cat("x1") == "bar" and len(store.regras(c)) == 2

    # importação nova já entra categorizada pela regra
    store.upsert(c, [("x3", "inter", "cartao 1", "concluido", -5.0, "Pingo no I 2", "2026-07-01")])
    assert cat("x3") == "bar"

    # padrão mais longo ganha do mais curto
    store.add_regra(c, "pingo no i 2", "outro lugar")
    assert cat("x3") == "outro lugar" and cat("x1") == "bar"

    # lista de trechos por vírgula: uma regra por trecho, todas na mesma categoria
    store.upsert(c, [("x4", "inter", "cartao 1", "concluido", -30.0, "BAR DO ZE", "2026-07-02"),
                     ("x5", "inter", "cartao 1", "concluido", -40.0, "BOTECO", "2026-07-03")])
    assert store.add_regra(c, "bar do ze, , boteco", "lazer") == 2
    assert (cat("x4"), cat("x5")) == ("lazer", "lazer")   # vazio no meio é ignorado
    assert len(store.regras(c)) == 5

    c.execute("DELETE FROM regras")
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'x%'")
    c.commit()
    assert store.recategoriza(c) == 0

    # --- perna órfã da transferência entre contas próprias não pode virar entrada
    store.add_regra(c, "-rafael rocha", "interno")
    store.upsert(c, [
        ("z1", "inter", "pix enviado", "ok", -3749.92, "Cp :10573521-Rafael Rocha", "2026-07-02"),
        ("z2", "mercado_pago", "bank_transfer", "ok", 3749.92, "", "2026-07-02T06:40:15"),
        ("z3", "mercado_pago", "bank_transfer", "ok", 3749.92, "", "2026-07-09T06:40:15"),
    ])
    assert cat("z1") == "interno" and cat("z2") == "interno"   # par casado: some do fluxo
    assert cat("z3") != "interno"                              # sem par: entrada de verdade
    c.execute("DELETE FROM regras")
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'z%'")
    c.commit()

# --- MP: operação de saída vira valor negativo
import mp_sync  # noqa: E402
r = mp_sync.to_row({"id": 99, "transaction_amount": 50.0, "operation_type": "regular_payment",
                    "payment_type_id": "credit_card", "status": "approved",
                    "description": "Uber", "date_created": "2026-07-10T12:00:00.000-03:00",
                    "collector_id": 999}, meu_id=123)
assert r == ("mp_99", "mercado_pago", "credit_card", "approved", -50.0, "Uber", "2026-07-10T12:00:00")
assert store.categoriza(r[5]) == "transporte"
# collector_id == meu_id -> entrada (eu recebi)
r2 = mp_sync.to_row({"id": 100, "transaction_amount": 50.0, "operation_type": "regular_payment",
                     "payment_type_id": "account_money", "status": "approved",
                     "description": "Rendimiento", "date_created": "2026-07-11T09:00:00.000-03:00",
                     "collector_id": 123}, meu_id=123)
assert r2[4] == 50.0  # positivo: eu sou o collector
assert store.categoriza(f"{r2[2]} {r2[5]}") == "rendimento"  # MP rendimento identified

# --- dash: página renderiza (pega placeholder trocado) e upload multipart é lido
import io  # noqa: E402
import dash  # noqa: E402

pagina = dash.render({})
assert "<h1>Extrato unificado" in pagina and "{" not in pagina.split("<style>")[0]
assert "Farmácia São João" in dash.render({"cat": ["saude"]})
assert "Farmácia São João" not in dash.render({"cat": ["mercado"]})

# formatação pt-BR: dinheiro com vírgula decimal, data e mês por extenso
assert dash.brl(1234.56) == "1.234,56" and dash.brl(-18.5) == "-18,50"
assert dash.brl(0) == "0,00" and dash.mil(1174) == "1.174"
assert dash.dia_br("2026-07-19") == "19 jul 2026" and dash.mes_br("2026-07") == "jul/26"
assert "R$ 1.324,46" in pagina, "total do período tem que sair formatado em pt-BR"

# atalho de período: dias=N virou de/até no servidor e o chip certo acendeu
import datetime  # noqa: E402

p90 = dash.render({"dias": ["90"], "cat": ["saude"]})
assert f'name=de value="{(datetime.date.today() - datetime.timedelta(days=90)).isoformat()}"' in p90
assert f'name=ate value="{datetime.date.today().isoformat()}"' in p90
assert "<a class=on href='?cat=saude&amp;dias=90'>90d</a>" in p90     # mantém os outros filtros
assert "<a class=on" in dash.render({}) and "<a class=on" not in dash.render({"de": ["2026-01-01"]})

# "onde mais gastei": parcelas da mesma compra somam numa linha só, não 1 linha por parcela
with store.conn() as c:
    store.upsert(c, [("y1", "inter", "cartao 1", "ok", -50.0, "LOJA X (Parcela 01 de 02)", "2026-07-08"),
                     ("y2", "inter", "cartao 1", "ok", -50.0, "LOJA X (Parcela 02 de 02)", "2026-07-09")])
onde = dash.render({}).split("Onde mais gastei")[1].split("</tbody>")[0]
assert onde.count("LOJA X") == 1 and "Parcela" not in onde, onde
assert "100,00" in onde, onde
with store.conn() as c:
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'y%'"); c.commit()

# triagem: sem descrição (Mercado Pago) o padrão vem do tipo, senão a fila apareceria vazia
with store.conn() as c:
    store.upsert(c, [("z1", "mercado_pago", "bank_transfer", "approved", -70.0, "", "2026-07-11"),
                     ("z2", "mercado_pago", "bank_transfer", "approved", -30.0, "", "2026-07-12")])
fila = dash.render({}).split('em "outros"')[1].split("</tbody>")[0]
assert 'value="bank_transfer"' in fila, fila     # padrão da regra veio do tipo
assert "-100,00" in fila, fila                   # os dois lançamentos agrupados
with store.conn() as c:
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'z%'"); c.commit()

# nota: descrição à mão para lançamento sem descrição, e sobrevive ao resync
with store.conn() as c:
    store.upsert(c, [("n1", "mercado_pago", "bank_transfer", "approved", -80.0, "", "2026-07-13")])
    assert 'name=id value="n1"' in dash.render({}), "sem descrição -> campo editável no razão"
    store.set_nota(c, "n1", " aluguel garagem ")
    assert "aluguel garagem" in dash.render({})
    store.upsert(c, [("n1", "mercado_pago", "bank_transfer", "approved", -80.0, "", "2026-07-13")])
    assert c.execute("SELECT nota FROM movimentacoes WHERE id='n1'").fetchone()[0] == "aluguel garagem"
    store.set_nota(c, "n1", "")
    assert c.execute("SELECT nota FROM movimentacoes WHERE id='n1'").fetchone()[0] is None
    try:
        store.set_nota(c, "naoexiste", "x"); assert False
    except ValueError:
        pass
    c.execute("DELETE FROM movimentacoes WHERE id='n1'"); c.commit()

# razão: uma faixa (tbody) por dia e o fio acumulado somado na ordem cronológica
# tupla do razão: data,origem,tipo,descricao,status,categoria,valor,id,nota
LINHAS = [("2026-07-20T10:00:00", "inter", "pix enviado", "B", "concluido", "outros", -30.0, "r1", None),
          ("2026-07-19", "inter", "pix recebido", "A", "concluido", "salario", 100.0, "r2", None)]
rz = dash.razao(LINHAS)                                  # linhas chegam em data DESC
assert rz.count("<tbody") == 2, rz
assert "20 jul 2026" in rz and "19 jul 2026" in rz, rz
assert "-30,00" in rz and "100,00" in rz, rz
# acumulado: 19/07 fecha em 100, 20/07 em 70. Valores numéricos na coluna Acum.
assert "70,00" in rz and "100,00" in rz, rz
assert "sem dados" in dash.razao([])
# status do caminho felizial não polui a coluna; exceção aparece
assert "concluido" not in rz and "refunded" in dash.razao(
    [("2026-07-20", "mercado_pago", "pix", "C", "refunded", "outros", -1.0, "r3", None)])

BODY = (b"--X\r\nContent-Disposition: form-data; name=\"pdf\"; filename=\"a.pdf\"\r\n"
        b"Content-Type: application/pdf\r\n\r\n%PDF-fake\r\n--X--\r\n")


class FakeH(dash.H):
    def __init__(self, body):  # sem super(): BaseHTTPRequestHandler já atenderia a conexão
        self.headers = {"Content-Type": "multipart/form-data; boundary=X",
                        "Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)


assert FakeH(BODY).arquivos() == [("a.pdf", b"%PDF-fake")]

# --- Investimentos: sub-categorias e seção dedicada
# Inter rendimentos
assert store.categoriza("credito rendimento Rend.Poup 07/2026") == "rendimento"
assert store.categoriza("credito juros s/capital JUROS S/CAPITAL PETR4") == "rendimento"
assert store.categoriza("credito provento DIVIDENDO VALE3") == "rendimento"
# MP rendimentos (rendimiento = espanhol usado pelo MP na descrição)
assert store.categoriza("account_money rendimiento") == "rendimento"
# Inter aplicações
assert store.categoriza("debito tesouro direto Prot.1234 IPCA+ 2029") == "aplicacao"
assert store.categoriza("debito b3 Liquidacao Compra BV 01/08") == "aplicacao"
# Resgates
assert store.categoriza("credito renda fixa Resgate CDB 120% CDI") == "resgate"
assert store.categoriza("resgate tesouro Prot.5678 SELIC 2027") == "resgate"
# investimentos não aparecem no razão do dashboard
with store.conn() as c:
    store.upsert(c, [
        ("inv1", "inter", "debito tesouro direto", "concluido", -500.0, "Prot.1234 IPCA+ 2029", "2026-07-10"),
        ("inv2", "inter", "credito rendimento", "concluido", 12.50, "Rend.Poup 07/2026", "2026-07-15"),
        ("inv3", "mercado_pago", "account_money", "approved", 3.20, "Rendimiento", "2026-07-16"),
    ])
pg = dash.render({})
# investimentos section shows the data
assert "Investimentos" in pg
assert "Prot.1234 IPCA+ 2029" in pg  # appears in investment section
# aplicação (saída pra investimento) usa cor própria, não o vermelho de gasto
assert "inv-apl'>-500,00" in pg
# razão does NOT show investment rows
razao_part = pg.split("Razão")[1] if "Razão" in pg else ""
assert "Prot.1234 IPCA+ 2029" not in razao_part
# filtrar uma categoria fora do fluxo = consultá-la: entra no razão e nos totais
apl = dash.render({"cat": ["aplicacao"]})
assert "Prot.1234 IPCA+ 2029" in apl.split("Razão")[1]
assert "500,00" in apl.split("Gasto")[1][:400]     # o gasto deixa de ser zero
assert "Prot.1234 IPCA+ 2029" not in dash.render({"cat": ["mercado"]}).split("Razão")[1]
assert "Rend.Poup 07/2026" not in razao_part
assert "Rendimiento" not in razao_part
with store.conn() as c:
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'inv%'"); c.commit()

# --- Parcelado: cronograma deduzido do sufixo "(Parcela N de T)"
import datetime as _dt  # noqa: E402

with store.conn() as c:
    store.upsert(c, [
        # 6x de 130 comprada em 05/jun (antes do fechamento dia 15) -> 1ª parcela na fatura de jun
        (f"pc{n}", "inter", "cartao 5555****4674", "concluido", -130.0,
         f"RELOJOARIA (Parcela {n:02d} de 06)", "2026-06-05") for n in (1, 2)
    ] + [
        # 2x de 50 comprada em 20/mai (depois do fechamento) -> 1ª parcela só na fatura de jun
        ("pq1", "inter", "cartao 5555****4674", "concluido", -50.0,
         "LOJA QUITADA (Parcela 01 de 02)", "2026-05-20"),
        ("pq2", "inter", "cartao 5555****4674", "concluido", -50.0,
         "LOJA QUITADA (Parcela 02 de 02)", "2026-05-20"),
    ])
    # data fixa: em 16/set a fatura de setembro já fechou (dia 15)
    compras, meses = store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))
    por_loja = {p.loja: p for p in compras}
    rel = por_loja["RELOJOARIA"]
    assert rel.parcelas == 6 and rel.valor_parcela == 130.0
    assert rel.primeira == "2026-06" and rel.ultima == "2026-11"
    assert rel.pagas == 4 and rel.restantes == 2, rel      # jun,jul,ago,set fechadas
    assert rel.aberto == 260.0 and rel.completo is False   # só 2 das 6 parcelas importadas
    assert rel.valor_total == 780.0                        # estimado: 6 × 130
    q = por_loja["LOJA QUITADA"]
    assert q.primeira == "2026-06" and q.restantes == 0 and q.completo is True
    assert q.valor_total == 100.0 and q.aberto == 0.0
    assert compras[0].loja == "RELOJOARIA"                 # em aberto vem antes do quitado
    assert meses == [("2026-10", 130.0), ("2026-11", 130.0)], meses
    # borda do fechamento: o débito da fatura cai no próprio dia 15, então nesse dia ela
    # já conta como paga; no dia 14 ainda não (uma parcela a menos)
    assert store.parcelamentos(c, hoje=_dt.date(2026, 9, 15))[0][0].pagas == 4
    assert store.parcelamentos(c, hoje=_dt.date(2026, 9, 14))[0][0].pagas == 3
    # valor da parcela vem da parcela de maior número, não do maior valor: o arredondamento
    # cai na 1ª parcela, então projetar pelo valor dela deixaria o futuro alguns centavos alto
    store.upsert(c, [
        ("pr1", "inter", "cartao 1", "concluido", -100.02, "ARRED (Parcela 01 de 04)", "2026-09-05"),
        ("pr2", "inter", "cartao 1", "concluido", -100.00, "ARRED (Parcela 02 de 04)", "2026-09-05"),
    ])
    arr = [p for p in store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))[0]
           if p.loja == "ARRED"][0]
    # 4x, 1ª na fatura de set (já cobrada em 16/set) -> 3 em aberto a 100,00 (não a 100,02)
    assert arr.valor_parcela == 100.00 and arr.aberto == 300.00, arr
    # duas compras iguais no mesmo dia são dois parcelamentos, não um com valor dobrado
    store.upsert(c, [
        ("pd1", "inter", "cartao 1", "concluido", -20.0, "DUPLA (Parcela 01 de 02)", "2026-08-10"),
        ("pd2", "inter", "cartao 1", "concluido", -20.0, "DUPLA (Parcela 02 de 02)", "2026-08-10"),
        ("pd3", "inter", "cartao 1", "concluido", -20.0, "DUPLA (Parcela 01 de 02)", "2026-08-10"),
        ("pd4", "inter", "cartao 1", "concluido", -20.0, "DUPLA (Parcela 02 de 02)", "2026-08-10"),
    ])
    dup = [p for p in store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))[0] if p.loja == "DUPLA"]
    assert len(dup) == 2 and all(p.valor_total == 40.0 for p in dup), dup
    # estorno de parcela vem positivo: é devolução, não cobrança — não pode virar parcelamento
    # (senão "em aberto" soma dinheiro que voltou pro bolso)
    store.upsert(c, [("pe1", "inter", "cartao 1", "concluido", 40.0,
                      "ESTORNADA (Parcela 01 de 04)", "2026-08-10")])
    assert not [p for p in store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))[0]
                if p.loja == "ESTORNADA"]
    # total de parcelas inválido não pode chegar na divisão da barra de progresso
    store.upsert(c, [("pz1", "inter", "cartao 1", "concluido", -10.0,
                      "ZERADA (Parcela 00 de 00)", "2026-08-10")])
    assert not [p for p in store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))[0]
                if p.loja == "ZERADA"]
    # nome de loja que contém o próprio sufixo: vale o último "(Parcela N de T)" da linha
    store.upsert(c, [("pn1", "inter", "cartao 1", "concluido", -10.0,
                      "BAR (Parcela 01 de 02) X (Parcela 01 de 03)", "2026-08-10")])
    nome = [p for p in store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))[0]
            if p.loja.startswith("BAR")][0]
    assert nome.loja == "BAR (Parcela 01 de 02) X" and nome.parcelas == 3, nome
    # compra futura: nada cobrado ainda, tudo em aberto
    store.upsert(c, [("pf1", "inter", "cartao 1", "concluido", -10.0,
                      "FUTURA (Parcela 01 de 03)", "2026-12-20")])
    fut = [p for p in store.parcelamentos(c, hoje=_dt.date(2026, 9, 16))[0]
           if p.loja == "FUTURA"][0]
    assert fut.pagas == 0 and fut.primeira == "2027-01" and fut.aberto == 30.0, fut

pg = dash.render({})
parc = pg.split("Parcelado")[1].split("Investimentos")[0]
assert "RELOJOARIA" in parc and "nov/26" in parc, parc[:800]
assert "LOJA QUITADA" in parc                      # quitados na tabela recolhida
assert "4/6" in parc                               # progresso da compra em aberto
# seção não segue o filtro de período: compromisso futuro não sai da tela ao filtrar o passado
assert "RELOJOARIA" in dash.render({"de": ["2026-01-01"], "ate": ["2026-01-31"]}).split(
    "Parcelado")[1].split("Investimentos")[0]
with store.conn() as c:
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'p%'"); c.commit()

# --- Conferência de saldo: Δ informado vs Σ lançado, cartão fora do caixa
with store.conn() as c:
    store.upsert(c, [
        ("cf1", "inter", "pix", "concluido", -100.0, "Aluguel", "2026-07-20"),
        ("cf2", "inter", "credito", "concluido", 300.0, "Salario", "2026-07-25"),
        ("cf3", "inter", "cartao 5364****", "concluido", -50.0, "Ifood", "2026-07-22"),
    ])
    store.set_saldo(c, "2026-07-15", 1000.0)
    # 1000 - 100 + 300 = 1200 se tudo estivesse rastreado; informa 1150 -> faltam 50
    store.set_saldo(c, "2026-07-31", 1150.0, caixinhas=200.0, inter=950.0, fatura=50.0)
    conf = store.conferencia(c)
    assert conf[0][0] == "2026-07-31" and conf[0][5] == 150.0  # Δ informado
    assert conf[0][6] == 200.0                                 # Σ lançado (cartão fora)
    assert conf[0][7] == -50.0                                 # não rastreado
    assert conf[1][5:] == (None, None, None)                   # foto mais antiga não compara
    # fatura em aberto: sem pagamento de fatura no extrato, soma toda compra de cartão
    assert store.fatura_aberta(c) == 50.0
    # sobrescrever a mesma data não duplica
    store.set_saldo(c, "2026-07-31", 1200.0)
    assert len(store.conferencia(c)) == 2 and store.conferencia(c)[0][7] == 0.0
assert "Conferência" in dash.render({})
with store.conn() as c:
    c.execute("DELETE FROM movimentacoes WHERE id LIKE 'cf%'")
    c.execute("DELETE FROM saldos"); c.commit()

# --- B3: extrato de movimentação -> tabela própria (não entra em movimentacoes)
import b3_pdf  # noqa: E402

B3_TXT = (
    "RAFAEL ROCHA RIBEIRO | CPF/CNPJ: 12134895632\n"
    "Filtros aplicados\n"
    "Data Inicial: 31/07/2025 | Data Final: 31/07/2026\n"
    "31 de julho de 2026\n"
    "Movimentação Produto Instituição Quantidade Preço\n"
    "Unitário\n"
    "Valor da\n"
    "Operação\n"
    "Juros Sobre\n"                                    # label quebrado em 3 linhas
    "Capital\n"
    "Próprio\n"
    "BBDC4 - BANCO BRADESCO S/A\n"
    "INTER DISTRIBUIDORA DE TITULOS E VALORES MOBILIARIOS LTDA\n"
    "2 R$ 0,39 R$ 0,66\n"
    "Direito de\n"
    "Subscrição\n"
    "KNSC12 - KINEA SECURITIES FII\n"
    "INTER DISTRIBUIDORA DE TITULOS E VALORES MOBILIARIOS LTDA\n"
    "14 R$ - R$ -\n"                                   # sem valor: direito de subscrição
    "14 de julho de 2026\n"
    "Movimentação Produto Instituição Quantidade Preço\n"
    "Transferência\n"
    "- Liquidação HGLG11 - PÁTRIA LOG - FDO INV IMOB\n"
    "INTER DISTRIBUIDORA DE TITULOS E VALORES MOBILIARIOS LTDA\n"
    "6 R$ 149,39 R$ 896,34\n"
    "Rendimento Compra Tesouro IPCA+ 2035 INTER DISTRIBUIDORA LTDA 0,36 R$ 139,08 R$ 50,07\n"
    "Extrato de Movimentação\n"
    "acesse investidor.B3.com.br 1/65\n"
)
b3 = b3_pdf.parse_texto(B3_TXT)
assert len(b3) == 4, b3
assert b3[0] == ("2026-07-31", "Juros Sobre Capital Próprio", "BBDC4",
                 "Juros Sobre Capital Próprio BBDC4 - BANCO BRADESCO S/A INTER DISTRIBUIDORA "
                 "DE TITULOS E VALORES MOBILIARIOS LTDA", 2.0, 0.39, 0.66), b3[0]
assert b3[1][1:3] == ("Direito de Subscrição", "KNSC12") and b3[1][6] == 0.0, b3[1]
assert b3[2][:3] == ("2026-07-14", "Transferência - Liquidação", "HGLG11"), b3[2]
assert b3[3][1] == "Rendimento" and b3[3][2] == "" and b3[3][4:] == (0.36, 139.08, 50.07), b3[3]

# idempotência: reimportar o mesmo extrato não duplica
with store.conn() as c:
    rows = b3_pdf.to_rows(b3)
    store.upsert_b3(c, rows)
    store.upsert_b3(c, b3_pdf.to_rows(b3_pdf.parse_texto(B3_TXT)))
    assert c.execute("SELECT COUNT(*) FROM b3_mov").fetchone()[0] == 4
    # provento soma só o que é renda; liquidação de compra fica fora
    p = ",".join("?" * len(b3_pdf.PROVENTOS))
    soma = c.execute(f"SELECT SUM(valor) FROM b3_mov WHERE mov IN ({p})",
                     list(b3_pdf.PROVENTOS)).fetchone()[0]
    assert round(soma, 2) == 50.73, soma      # 0,66 (JCP) + 50,07 (juros Tesouro)

# dash: seção de investimentos mostra o ativo; razão e gasto seguem sem os eventos da B3
pg = dash.render({})
assert "eventos da B3 por ativo" in pg and "BBDC4" in pg, "ativo da B3 não apareceu"
assert "HGLG11" not in pg.split("Razão")[1], "evento da B3 não pode entrar no razão"
assert "R$ 1.324,46" in pg, "gasto do período não pode mudar por causa da B3"
with store.conn() as c:
    c.execute("DELETE FROM b3_mov"); c.commit()

print("OK")
