# SDD-002: Stdlib Only + pypdf

**Status**: Aceita  
**Data**: 2025-07  
**Contexto**: Manter o projeto simples, sem peso de framework.

## Decisão

O projeto usa apenas a biblioteca padrão do Python 3.9+ (stdlib). A única exceção
é `pypdf`, necessária para extrair texto de PDF — e isolada em `inter_pdf.py`.

## Motivação

- Sem `requirements.txt` com dezenas de linhas, sem conflito de versão, sem virtualenv obrigatório.
- `http.server` é suficiente para um dashboard local de uma página.
- `urllib` resolve o REST do Mercado Pago (3 endpoints, sem paginação complexa de headers).
- `sqlite3` já vem no Python e cobre as queries analíticas necessárias.
- `pypdf` é a exceção mínima: PDF não é texto, precisa de lib. Mas fica confinada num módulo.

## Consequências

- **Positivas**: `pip install pypdf` e pronto. Setup em 5 segundos.
- **Negativas**: Sem ORM (queries SQL manuais), sem framework web (roteamento manual), sem requests (urllib verboso).
- **Trade-off aceito**: O código é mais verboso que com Flask+requests, mas o custo de manutenção de deps é zero.

## Alternativas Descartadas

- Flask/FastAPI: overkill para uma página, adicionaria ASGI/WSGI e templates.
- requests: confortável mas adiciona dep transitiva (urllib3, certifi, charset_normalizer, idna).
- pdfplumber/markitdown: embrulham a mesma extração de texto que pypdf faz, com dependências extras.
- SQLAlchemy: overhead de ORM para 2 tabelas e 8 queries.
