"""Sync Mercado Pago -> SQLite. Uso: python mp_sync.py [dias]  (default 30)

Token lido do ambiente ou do arquivo .env — ver creds.py e .env.example.
Rodável em cron/Agendador de Tarefas.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import creds
import store

API = "https://api.mercadopago.com/v1/payments/search"
LIMIT = 50
BR = timezone(timedelta(hours=-3))


def fetch(token, begin, end):
    offset = 0
    while True:
        qs = urllib.parse.urlencode({
            "sort": "date_created", "criteria": "desc",
            "range": "date_created", "begin_date": begin, "end_date": end,
            "limit": LIMIT, "offset": offset,
        })
        req = urllib.request.Request(f"{API}?{qs}", headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            # RuntimeError, não sys.exit: o dash chama isso dentro do handler HTTP
            raise RuntimeError(f"MP API {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        results = data.get("results", [])
        if not results:
            return
        yield from results
        offset += LIMIT
        if offset >= data.get("paging", {}).get("total", 0):
            return


def me(token):
    """Meu user id no MP (quem é dono do token)."""
    req = urllib.request.Request("https://api.mercadopago.com/users/me",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["id"]


def fetch_one(token, payment_id):
    """GET /v1/payments/{id} — retorna payment completo com payer.first_name etc."""
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError:
        return None


def _payer_name(p):
    """Extrai nome do pagador de todos os campos possíveis do payment object."""
    # 1) payer.first_name / last_name (campo padrão)
    payer = p.get("payer") or {}
    parts = [payer.get("first_name") or "", payer.get("last_name") or ""]
    name = " ".join(x for x in parts if x).strip()
    if name:
        return name
    # 2) point_of_interaction.transaction_data.payer_name (PIX P2P)
    poi = p.get("point_of_interaction") or {}
    td = poi.get("transaction_data") or {}
    name = (td.get("payer_name") or "").strip()
    if name:
        return name
    # 3) payer email prefix como último recurso (melhor que vazio)
    email = payer.get("email") or ""
    if email and "@" in email:
        prefix = email.split("@")[0]
        # ignora emails genéricos de teste
        if prefix not in ("null", "test_payer", ""):
            return prefix
    return ""


def _contraparte(p, meu_id):
    """Nome do contraparte: se eu paguei, nome do collector; se recebi, nome do payer."""
    if str(p.get("collector_id")) != str(meu_id):
        # eu paguei -> contraparte é quem recebeu (collector não vem com nome na search,
        # mas description costuma ter; fallback vazio)
        return ""
    # eu recebi -> contraparte é quem pagou
    return _payer_name(p)


def to_row(p, meu_id=None):
    # sinal: sou o collector -> entrada; senão eu paguei -> saída.
    # operation_type não serve: Pix recebido vem como regular_payment igual a compra minha.
    valor = float(p.get("transaction_amount") or 0)
    if str(p.get("collector_id")) != str(meu_id):
        valor = -abs(valor)
    # tipo: payment_method_id é mais específico (pix, ted, boleto) que payment_type_id (bank_transfer)
    tipo = p.get("payment_method_id") or p.get("payment_type_id") or p.get("operation_type")
    # descrição: campo description, ou título do item, ou nome do contraparte
    desc = p.get("description") or (p.get("additional_info") or {}).get("items", [{}])[0].get("title") or ""
    if not desc.strip():
        desc = _contraparte(p, meu_id)
    return (f"mp_{p['id']}", "mercado_pago", tipo,
            p.get("status"), valor, desc, (p.get("date_created") or "")[:19])


def _enrich(payments, token, meu_id):
    """Para pagamentos recebidos (eu sou collector) sem nome do pagador, busca GET /v1/payments/{id}."""
    for p in payments:
        # Só enriquece se eu recebi E não tem nome do pagador
        if str(p.get("collector_id")) == str(meu_id):
            if not _payer_name(p):
                detail = fetch_one(token, p["id"])
                if detail:
                    # Mescla campos de payer e point_of_interaction da resposta completa
                    p["payer"] = detail.get("payer") or p.get("payer")
                    if detail.get("point_of_interaction"):
                        p["point_of_interaction"] = detail["point_of_interaction"]
        yield p


def sync(dias=30):
    """Baixa e grava. Devolve nº de movimentações. Usado pelo CLI e pelo dash."""
    end = datetime.now(BR)
    begin = end - timedelta(days=dias)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000-03:00")
    token = creds.access_token()
    meu_id = me(token)
    payments = list(fetch(token, fmt(begin), fmt(end)))
    enriched = _enrich(payments, token, meu_id)
    rows = [to_row(p, meu_id) for p in enriched]
    with store.conn() as c:
        return store.upsert(c, rows) if rows else 0


def backfill():
    """Busca nomes para movimentações MP existentes sem descrição. Idempotente."""
    token = creds.access_token()
    meu_id = me(token)
    with store.conn() as c:
        rows = c.execute(
            "SELECT id FROM movimentacoes "
            "WHERE origem='mercado_pago' AND (descricao IS NULL OR trim(descricao)='') "
            "ORDER BY data DESC"
        ).fetchall()
    if not rows:
        print("Nenhuma movimentação sem descrição.")
        return 0
    print(f"{len(rows)} movimentações sem descrição. Buscando nomes...")
    rs = store.regras(store.conn())
    updated = 0
    for i, (mid,) in enumerate(rows, 1):
        payment_id = mid.removeprefix("mp_")
        detail = fetch_one(token, payment_id)
        if not detail:
            continue
        row = to_row(detail, meu_id)
        # row = (id, origem, tipo, status, valor, desc, data)
        desc = row[5]
        if desc.strip():
            cat = store.categoriza(f"{row[2]} {desc}", rs)
            with store.conn() as c:
                c.execute("UPDATE movimentacoes SET descricao=?, categoria=? WHERE id=?",
                          (desc, cat, mid))
                c.commit()
            updated += 1
        if i % 20 == 0:
            print(f"  {i}/{len(rows)} verificados, {updated} atualizados...")
    print(f"Pronto: {updated}/{len(rows)} atualizados.")
    return updated


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill":
        try:
            backfill()
        except RuntimeError as e:
            sys.exit(str(e))
        return
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    try:
        n = sync(dias)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"Mercado Pago: {n} movimentações ({dias}d) -> {store.DB}")


if __name__ == "__main__":
    main()
