"""Helpers de formatação e parsing de valores brasileiros.

Compartilhado por inter_import, inter_pdf e dash. Centraliza a conversão
entre formatos BR (1.234,56) e float, e formatação de datas pt-BR.
"""
import re

# --- Parsing (texto BR -> Python) ---

def valor_br(s):
    """'R$ -1.234,56' / '-1.234,56' / '(1.234,56)' -> float. Vazio -> None."""
    s = (s or "").strip().replace("R$", "").replace("\xa0", " ").strip()
    if not s or s in ("-", "--"):
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = re.sub(r"[^\d,.]", "", s)
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")  # milhar . / decimal ,
    return -abs(float(s)) if neg else float(s)


def data_br(s):
    """'01/08/2026' -> '2026-08-01'. Devolve None se não for data."""
    m = re.match(r"\s*(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


# --- Formatação (Python -> texto BR) ---

MES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def brl(v):
    """float -> '1.234,56' (sem prefixo R$, com milhar)."""
    return f"{v:,.2f}".translate(str.maketrans(",.", ".,"))


def mil(k):
    """int -> '1.234' (milhar com ponto)."""
    return f"{k:,}".replace(",", ".")


def dia_br(s):
    """'2026-07-19' -> '19 jul 2026'."""
    return f"{s[8:10]} {MES[int(s[5:7]) - 1]} {s[:4]}"


def mes_br(s):
    """'2026-07' -> 'jul/26'."""
    return f"{MES[int(s[5:7]) - 1]}/{s[2:4]}"
