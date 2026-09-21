"""Importa extrato CSV do Banco Inter -> SQLite. Uso: python inter_import.py extrato.csv"""
import csv
import hashlib
import sys

import store
from fmt import valor_br, data_br  # noqa: F401 — re-exportados para retrocompatibilidade


def parse(path):
    """Pula metadados do header, acha linha de cabeçalho, devolve rows do store."""
    with open(path, encoding="latin-1", newline="") as f:
        linhas = list(csv.reader(f, delimiter=";"))
    # cabeçalho real = primeira linha cujo 1º campo contenha "data"
    i = next((n for n, l in enumerate(linhas) if l and "data" in l[0].strip().lower()), None)
    if i is None:
        sys.exit(f"{path}: cabeçalho não encontrado (esperado coluna 'Data ...')")
    head = [h.strip().lower() for h in linhas[i]]
    # keys em ordem de prioridade: "descri" ganha de "histórico" para a descrição
    col = lambda *keys: next((n for k in keys for n, h in enumerate(head) if k in h), None)
    c_val, c_desc, c_tipo = col("valor"), col("descri", "histor", "histór"), col("histor", "histór", "tipo")

    rows = []
    for l in linhas[i + 1:]:
        if not l or len(l) <= max(x for x in (c_val, c_desc) if x is not None):
            continue
        data = data_br(l[0])
        valor = valor_br(l[c_val]) if c_val is not None else None
        if not data or valor is None:
            continue  # linhas de saldo/rodapé
        desc = (l[c_desc] or "").strip() if c_desc is not None else ""
        tipo = (l[c_tipo] or "").strip() if c_tipo is not None else ""
        # ID determinístico: hash da linha crua -> reimportar não duplica
        rid = "inter_" + hashlib.sha256(";".join(l).encode("utf-8")).hexdigest()[:16]
        rows.append((rid, "inter", tipo or ("credito" if valor > 0 else "debito"), "concluido",
                     valor, desc, data))
    return rows


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python inter_import.py extrato.csv")
    rows = parse(sys.argv[1])
    with store.conn() as c:
        n = store.upsert(c, rows)
    print(f"Inter: {n} movimentações importadas -> {store.DB}")


if __name__ == "__main__":
    main()
