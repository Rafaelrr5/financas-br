# Arquitetura — Finance Tracker

## Visão Geral

Rastreador financeiro pessoal que unifica extratos do Banco Inter (PDF/CSV) e Mercado Pago
(API REST) num SQLite local, com categorização automática por keyword + regras manuais e
um dashboard web server-side-rendered.

```
┌──────────────────────────────────────────────────────────────────┐
│                        FONTES DE DADOS                            │
├──────────────┬───────────────────┬───────────────────────────────┤
│ inter_pdf.py │  inter_import.py  │         mp_sync.py            │
│ (PDF pypdf)  │  (CSV legado)     │  (REST /v1/payments/search)   │
└──────┬───────┴─────────┬─────────┴──────────────┬───────────────┘
       │                 │                        │
       └─────────────────┼────────────────────────┘
                         ▼
              ┌─────────────────────┐
              │      store.py       │
              │  Schema + upsert    │
              │  Categorização      │
              │  Regras manuais     │
              └──────────┬──────────┘
                         │
                    ┌────┴────┐
                    │ fin.db  │  (SQLite)
                    └────┬────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    ┌─────▼─────┐  ┌────▼────┐  ┌─────▼─────┐
    │  dash.py  │  │  cat.py │  │  Queries   │
    │  (HTTP)   │  │  (CLI)  │  │  diretas   │
    └───────────┘  └─────────┘  └───────────┘
```

## Módulos e Responsabilidades

| Módulo | Camada | Responsabilidade |
|--------|--------|------------------|
| `store.py` | Dados | Schema, conexão, upsert idempotente, categorização (keywords + regras), parcelamentos derivados |
| `mp_sync.py` | Ingestão | Pagina API do MP, normaliza sinal, monta row |
| `inter_pdf.py` | Ingestão | Extrai texto do PDF (pypdf), regex de extrato e fatura |
| `inter_import.py` | Ingestão | Parse de CSV legado do Inter |
| `b3_pdf.py` | Ingestão | Extrato de movimentação da B3 → tabela `b3_mov` (detalhe por ativo, fora do caixa) |
| `cat.py` | Interface CLI | CRUD de regras e fila de triagem |
| `dash.py` | Interface Web | Server HTTP, renderiza HTML, recebe uploads/POST |
| `creds.py` | Configuração | Lê as credenciais do Mercado Pago do ambiente ou de `.env` |
| `test_fin.py` | Verificação | Testes unitários e de integração |

## Fluxo de Dados

1. **Ingestão** — PDF, CSV ou API → lista de tuples `(id, origem, tipo, status, valor, descricao, data)`
2. **Categorização** — `store.categoriza(tipo + " " + descricao, regras)` aplica:
   - Regras manuais (tabela `regras`) — padrão mais longo ganha
   - Keywords fixas (`store.CATEGORIAS`) — primeira que casar ganha
   - Fallback: `"outros"`
3. **Upsert** — `INSERT … ON CONFLICT DO UPDATE` garante idempotência via ID determinístico
4. **Apresentação** — `dash.py` renderiza server-side; JS só faz fetch+replace sem framework

## Invariantes (nunca violar)

1. **Sinal**: negativo = saída de dinheiro, positivo = entrada. Sem exceção.
2. **Idempotência**: reimportar o mesmo arquivo/período nunca duplica. ID é hash do conteúdo.
3. **Regras > keywords**: regra manual sempre vence keyword fixa de `CATEGORIAS`.
4. **Padrão mais longo ganha**: entre regras, `"padaria do zé"` ganha de `"padaria"`.
5. **NAO_FLUXO**: categorias `aplicacao`, `resgate`, `rendimento`, `fatura`, `interno` são
   excluídas do gasto/entrada no resumo — são remanejo, não consumo.
6. **Stdlib only** (+pypdf): zero dependência extra. urllib, não requests. http.server, não Flask.
7. **SQLite local**: sem servidor, sem migration tool. Schema auto-criado na conexão.
8. **Sem auth no dash**: escuta só `127.0.0.1`. Impacto de CSRF = regra errada, revertível.
9. **Fatura Inter**: linhas com `+` (pagamento) são ignoradas — já contam no extrato.
10. **`categoriza()` recebe `tipo + " " + descricao`**: no Inter o significado está no tipo.
11. **Parcelamento é derivado, nunca gravado**: `store.parcelamentos()` reconstrói a compra a
    partir do sufixo `(Parcela N de T)` da descrição. Não existe tabela de parcelas — se
    existisse, um resync teria que reconciliá-la. Cronograma assume 1 parcela/mês a partir da
    primeira fatura depois da compra (`store.FECHAMENTO`), porque o extrato lança todas as
    parcelas com a data da compra original. Linha de parcela positiva é estorno e não entra
    (invariante 1). O valor projetado vem da parcela de maior número já importada: o
    arredondamento cai sempre na 1ª (93,68 + 93,66 + 93,66), então a mais recente é o melhor
    palpite para as que ainda vêm.

## Schema (SQLite)

```sql
CREATE TABLE movimentacoes (
    id        TEXT PRIMARY KEY,    -- "mp_<id>" | "inter_<sha256[:16]>"
    origem    TEXT NOT NULL,       -- 'mercado_pago' | 'inter'
    tipo      TEXT,                -- pix, cartao 5364****, credit_card, etc.
    status    TEXT,                -- concluido, approved, refunded...
    valor     REAL NOT NULL,       -- negativo = saída
    descricao TEXT,
    data      TEXT NOT NULL,       -- ISO 8601 (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS)
    categoria TEXT
);
CREATE INDEX ix_data ON movimentacoes(data);

-- eventos por ativo do extrato da B3. Não é caixa: o crédito do provento e a liquidação da
-- nota já vêm no extrato do Inter, então importar em movimentacoes contaria em dobro.
CREATE TABLE b3_mov (
    id      TEXT PRIMARY KEY,    -- "b3_<sha256[:16]>"
    data    TEXT NOT NULL,        -- YYYY-MM-DD
    mov     TEXT,                 -- Rendimento, Transferência - Liquidação, JCP...
    ticker  TEXT,                 -- 'HGLG11' ('' em CRA/CDB/Tesouro)
    produto TEXT,                 -- registro cru do PDF (fallback quando não há ticker)
    qtd     REAL, preco REAL, valor REAL
);

CREATE TABLE regras (
    padrao    TEXT PRIMARY KEY,    -- substring normalizada (sem acento, minúsculo)
    categoria TEXT NOT NULL
);
```

## Decisões Arquiteturais

As decisões fundamentais estão documentadas em `docs/decisions/`. Resumo:

- **SDD-001**: Credenciais fora do código — ambiente ou `.env` local, nunca versionadas
- **SDD-002**: Stdlib only + pypdf — zero framework, zero ORM
- **SDD-003**: Categorização keyword + regras manuais (não ML)
- **SDD-004**: ID determinístico por hash (não autoincrement)
- **SDD-005**: Dashboard server-side rendered (não SPA, não API JSON)
- **SDD-006**: Sem auth — localhost only, impacto baixo
- **SDD-007**: NAO_FLUXO — investimento/fatura fora do gasto de consumo

## Extensibilidade

Para adicionar uma **nova fonte de dados**:
1. Criar módulo de ingestão (`nova_fonte.py`)
2. Gerar rows no formato `(id, origem, tipo, status, valor, descricao, data)`
3. Chamar `store.upsert(c, rows)`
4. ID deve ser determinístico (hash do conteúdo) para idempotência
5. `origem` nova exige alterar o CHECK constraint em `store.conn()`

Para adicionar uma **nova categoria**:
- Via código: adicionar no dict `store.CATEGORIAS` (ordem importa)
- Via regra: `python cat.py "trecho" categoria` — categoria nova é só um nome novo

Para adicionar uma **nova seção no dashboard**:
- Adicionar query no `render()`, placeholder no `PAGE`, trecho no HTML
- Zero JS necessário para dados estáticos; fetch+replace já cuida do resto
