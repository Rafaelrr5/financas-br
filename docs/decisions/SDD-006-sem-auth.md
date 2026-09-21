# SDD-006: Sem Autenticação no Dashboard

**Status**: Aceita  
**Data**: 2025-07  
**Contexto**: Dashboard roda localmente, escutando em 127.0.0.1:8000.

## Decisão

O servidor HTTP não implementa autenticação, CSRF token, ou controle de acesso.

## Motivação

- Bind em `127.0.0.1`: só processos locais alcançam.
- Único usuário: não há multitenancy.
- Pior caso de CSRF: outra aba do browser poderia fazer POST /regra com um padrão errado.
  Impacto = uma regra de categoria incorreta. Reversível com `cat.py --rm`.

## Consequências

- **Positivas**: Zero complexidade de sessão/token/login.
- **Negativas**: Se alguém expuser a porta (tunelamento, proxy reverso), os dados ficam abertos.
- **Mitigação**: README documenta que é localhost-only. Bind explícito em 127.0.0.1, não 0.0.0.0.

## Quando Revisitar

- Se o app for acessado de outra máquina na rede.
- Se o POST /regra ganhar impacto destrutivo (hoje é só texto, sem DELETE de dados).
