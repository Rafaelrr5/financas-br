"""Schema + upsert + categorização. Compartilhado por mp_sync, inter_import e dash."""
import collections
import datetime
import os
import re
import sqlite3
import unicodedata

DB = os.getenv("FIN_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fin.db"))

# ponytail: keywords em dict simples. Trocar por tabela no SQLite se virar edição frequente.
# Ordem importa: 1ª categoria que casar ganha. Investimento e fatura vêm antes de
# transferencia porque "Debito B3"/"Pagamento fatura" também parecem transferência.
CATEGORIAS = {
    # rendimento: juros, proventos, dividendos — renda passiva do investimento
    "rendimento": ["rendimento", "provento", "prov *", "juros s/capital", "dividendo",
                   "juros td", "juros cdb", "juros lci", "juros lca",
                   "rendimiento", "yield", "earnings"],
    # resgate: dinheiro voltando do investimento pra conta
    "resgate": ["resgate", "vencimento cdb", "vencimento lci", "vencimento lca",
                "credito renda fixa", "credito td", "credito tesouro"],
    # aplicacao: dinheiro saindo da conta pra investir
    "aplicacao": ["b3", "tesouro", "renda fixa", "online td", "compra td",
                  "nota bov", "nota negociacao", "liquidacao",
                  "cdb", "ntn", "lci", "lca", " cra ", "irrf",
                  "debito tesouro", "debito b3", "debito renda fixa"],
    "fatura": ["fatura cartao", "pagamento fatura", "pagto debito automatico"],
    "mercado": ["mercado", "supermerc", "carrefour", "assai", "atacad", "pao de acucar",
                "hortifruti", "hortimar", "quitanda", "bh comercio"],
    "transporte": ["uber", "99app", "99*", "taxi", "posto", "ipiranga", "shell",
                   "combustivel", "estacion", "blablacar"],
    "saude": ["farmac", "drogaria", "drogasil", "drogas", "raia", "araujo loja", "hospital",
              "clinica", "laborator"],
    "alimentacao": ["ifood", "ifd*", "rappi", "restaurante", "lanchonet", "padaria", "burger",
                    "pizza", "cafe", "mcdonald", "spoleto", "empada", "food", "zigpay"],
    "assinatura": ["netflix", "spotify", "amazon prime", "google", "apple", "microsoft", "openai", "claude"],
    "moradia": ["aluguel", "condominio", "enel", "cemig", "sabesp", "copasa", "energia", "agua", "internet", "vivo", "claro", "tim"],
    "salario": ["salario", "portabilidade", "13o sal"],
    "transferencia": ["pix", "ted", "doc", "transferencia"],
}


# Fora de gasto/entrada: investimento é remanejo de patrimônio, e pagamento de fatura
# já aparece como compra do cartão (contaria em dobro). Não aparecem no razão geral.
# 'interno' = pix entre contas próprias; marque via regra (ex.: padrão '-seu nome').
NAO_FLUXO = ("aplicacao", "resgate", "rendimento", "fatura", "interno")

# Categorias de investimento: usadas para agrupar na seção dedicada
INVESTIMENTO_CATS = ("aplicacao", "resgate", "rendimento")

# Compra no cartão de crédito não toca a conta: só vira saída quando a fatura é paga.
# Por isso fica fora da conferência de saldo (mas dentro do gasto de consumo).
FORA_DO_CAIXA = "tipo LIKE 'cartao %'"


def normaliza(s: str) -> str:
    """Minúsculo e sem acento: 'Farmácia' casa com keyword 'farmac'."""
    return "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(ch) != "Mn")


def categoriza(descricao: str, regras=()) -> str:
    """regras (padrão -> categoria, do usuário) ganham das keywords fixas."""
    d = normaliza(descricao)
    for padrao, cat in regras:
        if padrao in d:
            return cat
    for cat, palavras in CATEGORIAS.items():
        if any(p in d for p in palavras):
            return cat
    return "outros"


def conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS movimentacoes (
        id        TEXT PRIMARY KEY,
        origem    TEXT NOT NULL CHECK (origem IN ('mercado_pago','inter')),
        tipo      TEXT,
        status    TEXT,
        valor     REAL NOT NULL,
        descricao TEXT,
        data      TEXT NOT NULL,
        categoria TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_data ON movimentacoes(data)")
    # nota: descrição escrita à mão (pix/bank_transfer do MP vêm sem nada). Coluna separada de
    # `descricao` porque upsert sobrescreve descricao a cada resync — a nota tem que sobreviver.
    if not any(r[1] == "nota" for r in c.execute("PRAGMA table_info(movimentacoes)")):
        c.execute("ALTER TABLE movimentacoes ADD COLUMN nota TEXT")
    # eventos por ativo do extrato de movimentação da B3. Tabela separada, não `movimentacoes`:
    # o lado caixa já vem do extrato do Inter — misturar contaria em dobro (ver b3_pdf.py).
    c.execute("""CREATE TABLE IF NOT EXISTS b3_mov (
        id       TEXT PRIMARY KEY,
        data     TEXT NOT NULL,
        mov      TEXT,
        ticker   TEXT,
        produto  TEXT,
        qtd      REAL,
        preco    REAL,
        valor    REAL
    )""")
    # regras manuais: padrão (substring já normalizada) -> categoria. Categoria nova = nome novo.
    c.execute("CREATE TABLE IF NOT EXISTS regras (padrao TEXT PRIMARY KEY, categoria TEXT NOT NULL)")
    # saldos informados à mão: uma foto por data. Serve de âncora — o que o banco diz que
    # você tem versus o que as movimentações importadas explicam.
    c.execute("""CREATE TABLE IF NOT EXISTS saldos (
        data      TEXT PRIMARY KEY,
        total     REAL NOT NULL,
        caixinhas REAL NOT NULL DEFAULT 0,
        inter     REAL NOT NULL DEFAULT 0,
        fatura    REAL NOT NULL DEFAULT 0
    )""")
    return c


def set_saldo(c, data, total, caixinhas=0.0, inter=0.0, fatura=0.0):
    """Registra (ou sobrescreve) a foto de saldo de uma data."""
    if not data:
        raise ValueError("data do saldo é obrigatória")
    c.execute("INSERT INTO saldos VALUES (?,?,?,?,?) ON CONFLICT(data) DO UPDATE SET "
              "total=excluded.total, caixinhas=excluded.caixinhas, inter=excluded.inter, "
              "fatura=excluded.fatura", (data, total, caixinhas, inter, fatura))
    c.commit()


def conferencia(c, limite=12):
    """Por foto: Δ do saldo informado vs Σ do que entrou/saiu da conta desde a foto anterior.

    Devolve (data, total, caixinhas, inter, fatura, delta, movimentado, nao_rastreado).
    nao_rastreado != 0 significa dinheiro que se moveu sem lançamento importado — é o número
    que fecha (ou não) o mês. Cartão fica fora: a compra não muda saldo, o pagamento sim.
    ponytail: uma query por foto (máx. 12). Vira window function se virar histórico longo."""
    fotos = c.execute("SELECT data,total,caixinhas,inter,fatura FROM saldos "
                      "ORDER BY data DESC LIMIT ?", (limite + 1,)).fetchall()
    out = []
    for atual, ant in zip(fotos, fotos[1:] + [None]):
        if ant is None:  # foto mais antiga: sem anterior, nada a comparar
            out.append((*atual, None, None, None))
            break
        mov = c.execute(f"SELECT COALESCE(SUM(valor),0) FROM movimentacoes "
                        f"WHERE data > ? AND data <= ? AND NOT ({FORA_DO_CAIXA})",
                        (ant[0] + "T23:59:59", atual[0] + "T23:59:59")).fetchone()[0]
        delta = atual[1] - ant[1]
        out.append((*atual, delta, mov, delta - mov))
    return out


def fatura_aberta(c):
    """Σ das compras de cartão desde o último pagamento de fatura registrado no extrato.
    Compara com o valor da fatura que o app do Inter mostra: diferença = fatura não importada."""
    ult = c.execute("SELECT COALESCE(MAX(data),'') FROM movimentacoes "
                    "WHERE categoria='fatura'").fetchone()[0]
    return c.execute(f"SELECT COALESCE(SUM(-valor),0) FROM movimentacoes "
                     f"WHERE {FORA_DO_CAIXA} AND data > ?", (ult,)).fetchone()[0]


# "JIM.COM* RELOJOARIA B (Parcela 02 de 06)" -> loja, nº da parcela, total de parcelas.
# É o único lugar onde o Inter diz que a compra foi parcelada: não há coluna própria.
PARCELA = re.compile(r"^(?P<loja>.+?) \(Parcela (?P<n>\d+) de (?P<tot>\d+)\)$")

# Dia em que a fatura do Inter fecha. Compra até o dia 15 cai na fatura que fecha
# naquele mês; depois disso, na do mês seguinte.
FECHAMENTO = 15

Parcelamento = collections.namedtuple("Parcelamento", (
    "loja cartao categoria compra parcelas valor_parcela valor_total "
    "primeira ultima pagas restantes aberto completo"))


def soma_mes(ym, k):
    """'2026-11' + 3 -> '2027-02'."""
    y, m = int(ym[:4]), int(ym[5:7]) + k
    return f"{y + (m - 1) // 12:04d}-{(m - 1) % 12 + 1:02d}"


def _dist_mes(a, b):
    """Meses de 'aaaa-mm' a até 'aaaa-mm' b (b anterior a a -> negativo)."""
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def parcelamentos(c, hoje=None):
    """Compras parceladas reconstruídas a partir do sufixo '(Parcela N de T)'.

    Devolve (compras, meses):
      compras — lista de Parcelamento, em aberto primeiro (fim mais próximo antes),
                valores em módulo (positivos), como o resto dos agregados do dash.
      meses   — [(aaaa-mm, valor)] do que ainda vai cair em fatura, do mês atual em diante.

    O cronograma é DERIVADO, não importado: a fatura do Inter lança todas as parcelas
    com a data da compra original, então o banco não sabe em qual fatura cada uma cai.
    A conta assume uma parcela por mês a partir da primeira fatura depois da compra
    (fechamento dia `FECHAMENTO`). Carência, antecipação ou compra estornada saem errado.

    Valor da parcela = o da parcela de MAIOR NÚMERO já importada, não o maior valor: em
    todas as compras parceladas deste extrato o arredondamento cai na 1ª parcela (ex.:
    93,68 + 93,66 + 93,66), então a parcela mais recente é o melhor palpite para as que
    ainda vêm. Quando só a 1ª foi importada não há escolha, e o projetado fica alguns
    centavos alto. Total = parcelas × valor da parcela se nem toda parcela foi importada —
    `completo` diz se o total é somado ou estimado.
    """
    hoje = hoje or datetime.date.today()
    # último mês cuja fatura já foi cobrada. '<', não '<=': o débito automático da fatura
    # cai no próprio dia do fechamento (visto no extrato: 15/05, 15/06, 15/07), então no
    # dia 15 aquela fatura já saiu da conta. No dia 14 ainda não.
    fechado = hoje.strftime("%Y-%m")
    if hoje.day < FECHAMENTO:
        fechado = soma_mes(fechado, -1)

    # ocorrência: duas compras iguais no mesmo dia e mesma loja repetem o nº da parcela.
    # Sem isso as duas virariam um parcelamento só, com o dobro do valor numa parcela.
    # valor<0: linha de parcela positiva é estorno, não cobrança — somá-la inflaria o
    # "em aberto" (invariante 1: negativo = saída). "de 00" não existe em fatura real,
    # mas se o regex casar um lixo assim, tot=0 estouraria a divisão da barra de progresso.
    grupos, visto = collections.OrderedDict(), collections.Counter()
    for desc, tipo, cat, valor, data in c.execute(
            "SELECT descricao,tipo,categoria,valor,data FROM movimentacoes "
            "WHERE valor < 0 AND descricao LIKE '% (Parcela % de %)' "
            "ORDER BY data, descricao"):
        m = PARCELA.match(desc)
        if not m:
            continue
        n, tot = int(m["n"]), int(m["tot"])
        if tot < 1 or not 1 <= n <= tot:
            continue
        chave = (m["loja"], tot, data[:10], tipo or "")
        visto[chave + (n,)] += 1
        grupos.setdefault(chave + (visto[chave + (n,)],), {})[n] = (abs(valor), cat)

    compras = []
    for (loja, tot, compra, cartao, _oc), parc in grupos.items():
        maior = max(parc)
        valor_parcela, cat = parc[maior]
        completo = len(parc) == tot
        total = sum(v for v, _ in parc.values()) if completo else tot * valor_parcela
        primeira = compra[:7] if int(compra[8:10]) <= FECHAMENTO else soma_mes(compra[:7], 1)
        ultima = soma_mes(primeira, tot - 1)
        pagas = min(tot, max(0, _dist_mes(primeira, fechado) + 1))
        compras.append(Parcelamento(loja, cartao, cat, compra, tot, valor_parcela, total,
                                    primeira, ultima, pagas, tot - pagas,
                                    (tot - pagas) * valor_parcela, completo))
    # em aberto primeiro (o que termina antes no topo), quitados depois (o mais recente antes)
    compras.sort(key=lambda p: (p.restantes == 0,
                                _dist_mes("2000-01", p.ultima) * (1 if p.restantes else -1)))

    meses = collections.Counter()
    for p in compras:
        for k in range(p.pagas, p.parcelas):
            meses[soma_mes(p.primeira, k)] += p.valor_parcela
    return compras, sorted(meses.items())


def regras(c):
    """Padrão mais longo primeiro: 'padaria do zé' ganha de 'padaria'."""
    return c.execute("SELECT padrao,categoria FROM regras "
                     "ORDER BY length(padrao) DESC").fetchall()


def add_regra(c, padrao, categoria):
    """padrao: um trecho ou vários separados por vírgula ('uber, 99app, taxi') -> mesma categoria.
    ponytail: vírgula é sempre separador, então trecho que contém vírgula vira duas regras
    apontando pra mesma categoria (mesmo efeito, sobra regra a mais). Se virar problema,
    escapar com \\, no lugar de aceitar vírgula literal."""
    categoria = categoria.strip().lower()
    padroes = [p for p in (normaliza(x).strip() for x in padrao.split(",")) if p]
    if not padroes or not categoria:
        raise ValueError("padrão e categoria não podem ser vazios")
    c.executemany("INSERT INTO regras VALUES (?,?) ON CONFLICT(padrao) DO UPDATE SET "
                  "categoria=excluded.categoria", [(p, categoria) for p in padroes])
    return recategoriza(c)


def casa_internos(c):
    """Transferência entre contas próprias tem duas pernas: a que sai e a que entra.
    Só uma vem com o nome no extrato (regra '-rafael...' marca 'interno' no Inter); a outra
    chega no MP sem descrição e virava 'transferencia' — ou seja, entrada inflada.
    Casa por valor exato + mesmo dia + origem diferente e marca a perna órfã como interno.
    ponytail: par por (valor, dia). Se aparecer dia de dois pares de mesmo valor, casar por hora."""
    n = c.execute(
        f"UPDATE movimentacoes SET categoria='interno' WHERE categoria NOT IN "
        f"({','.join('?' * len(NAO_FLUXO))}) AND EXISTS ("
        "  SELECT 1 FROM movimentacoes b WHERE b.categoria='interno'"
        "  AND b.origem <> movimentacoes.origem AND b.valor = -movimentacoes.valor"
        "  AND substr(b.data,1,10) = substr(movimentacoes.data,1,10))", NAO_FLUXO).rowcount
    c.commit()
    return n


def set_nota(c, mid, nota):
    """Descrição à mão de um lançamento. Vazio limpa."""
    n = c.execute("UPDATE movimentacoes SET nota=? WHERE id=?",
                  ((nota or "").strip() or None, mid)).rowcount
    c.commit()
    if not n:
        raise ValueError(f"lançamento {mid!r} não encontrado")


def recategoriza(c):
    """Reaplica regras + keywords em tudo. Devolve nº de linhas que mudaram de categoria."""
    rs, mudou = regras(c), []
    for rid, tipo, desc, cat in c.execute(
            "SELECT id,tipo,descricao,categoria FROM movimentacoes").fetchall():
        nova = categoriza(f"{tipo} {desc}", rs)
        if nova != cat:
            mudou.append((nova, rid))
    c.executemany("UPDATE movimentacoes SET categoria=? WHERE id=?", mudou)
    c.commit()
    return len(mudou) + casa_internos(c)


def upsert(c, rows):
    """rows: iterável de (id, origem, tipo, status, valor, descricao, data). Idempotente."""
    # tipo entra na categorização: no extrato Inter o significado está nele
    # ("Debito Tesouro Direto", "Pagamento efetuado"), não na descrição.
    rs = regras(c)
    rows = [(*r, categoriza(f"{r[2]} {r[5]}", rs)) for r in rows]
    # colunas nomeadas: `nota` não vem do extrato e não pode ser sobrescrita no resync
    c.executemany("INSERT INTO movimentacoes "
                  "(id,origem,tipo,status,valor,descricao,data,categoria) VALUES (?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET status=excluded.status, valor=excluded.valor, "
                  "descricao=excluded.descricao, categoria=excluded.categoria", rows)
    c.commit()
    casa_internos(c)
    return len(rows)


def upsert_b3(c, rows):
    """rows: (id, data, mov, ticker, produto, qtd, preco, valor). Idempotente, sem categorização:
    evento da B3 não é fluxo de caixa, não entra em gasto/entrada nem no razão."""
    c.executemany("INSERT INTO b3_mov VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                  "mov=excluded.mov, ticker=excluded.ticker, produto=excluded.produto, "
                  "qtd=excluded.qtd, preco=excluded.preco, valor=excluded.valor", rows)
    c.commit()
    return len(rows)
