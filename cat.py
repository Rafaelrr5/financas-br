"""Categorização manual. Uma regra = substring -> categoria, aplicada a tudo (inclusive
importações futuras). Categoria nova é só um nome novo, não precisa cadastrar.

python cat.py                      # o que ainda está em 'outros' (maiores primeiro)
python cat.py "pingo no i" lazer   # cria/atualiza regra e recategoriza
python cat.py "uber,99app,taxi" transporte   # vários trechos -> mesma categoria
python cat.py --list               # regras existentes
python cat.py --rm "pingo no i"    # remove regra
"""
import sys

import store


def pendentes(c, limite=30):
    return c.execute(
        "SELECT tipo, descricao, COUNT(*), ROUND(SUM(valor),2) FROM movimentacoes "
        "WHERE categoria='outros' GROUP BY tipo, descricao "
        "ORDER BY ABS(SUM(valor)) DESC LIMIT ?", (limite,)).fetchall()


def main(argv):
    with store.conn() as c:
        if not argv:
            linhas = pendentes(c)
            if not linhas:
                return print("nada em 'outros'.")
            print(f"{'qtd':>4} {'total':>11}  tipo | descrição")
            for tipo, desc, n, total in linhas:
                print(f"{n:>4} {total:>11,.2f}  {tipo} | {desc}")
            print("\nCategorizar:  python cat.py \"<trecho da descrição>\" <categoria>")
        elif argv[0] == "--list":
            regras = store.regras(c)
            if not regras:
                return print("nenhuma regra.")
            por_cat = {}
            for padrao, cat in regras:
                por_cat.setdefault(cat, []).append(padrao)
            print(f"{len(regras)} regras em {len(por_cat)} categorias:\n")
            for cat in sorted(por_cat):
                items = por_cat[cat]
                print(f"  [{cat}] ({len(items)})")
                for p in sorted(items):
                    print(f"    {p}")
                print()
        elif argv[0] == "--rm" and len(argv) == 2:
            c.execute("DELETE FROM regras WHERE padrao=?", (store.normaliza(argv[1]),))
            print(f"regra removida; {store.recategoriza(c)} lançamentos recategorizados")
        elif len(argv) == 2:
            n = store.add_regra(c, argv[0], argv[1])
            print(f"'{argv[0]}' -> {argv[1]}: {n} lançamentos recategorizados")
        else:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
