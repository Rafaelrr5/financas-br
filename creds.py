"""Credenciais do Mercado Pago — lidas do ambiente, nunca versionadas.

Ordem de busca, primeira que existir ganha:

1. variável de ambiente (`MP_ACCESS_TOKEN`);
2. arquivo `.env` ao lado deste módulo (ignorado pelo git).

O arquivo `.env` existe porque o Agendador de Tarefas do Windows não herda
variáveis de ambiente com facilidade: dá para agendar `python mp_sync.py` sem
configurar nada no sistema, e o segredo continua fora do repositório.

Copie `.env.example` para `.env` e preencha. Sem token, só o Mercado Pago para
de funcionar — importação de PDF, categorização e dashboard seguem normais.
"""
import os

_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _do_arquivo():
    """Lê pares CHAVE=valor de .env. Sem dependência, sem interpolação."""
    if not os.path.exists(_ENV):
        return {}
    pares = {}
    with open(_ENV, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            pares[chave.strip()] = valor.strip().strip("'\"")
    return pares


_ARQUIVO = _do_arquivo()


def get(nome, obrigatorio=False):
    valor = os.environ.get(nome) or _ARQUIVO.get(nome, "")
    if obrigatorio and not valor:
        raise RuntimeError(
            f"{nome} não configurado. Copie .env.example para .env e preencha, "
            f"ou exporte {nome} no ambiente."
        )
    return valor


def access_token():
    """Token de produção do Mercado Pago. Levanta RuntimeError se faltar."""
    return get("MP_ACCESS_TOKEN", obrigatorio=True)


# Só usados quando existir OAuth (client id/secret) ou checkout no browser
# (public key). Opcionais: devolvem "" quando não configurados.
def client_id():
    return get("MP_CLIENT_ID")


def client_secret():
    return get("MP_CLIENT_SECRET")


def public_key():
    return get("MP_PUBLIC_KEY")
