# Guia de Contribuição

## Setup

```bash
pip install pypdf    # única dependência externa
python test_fin.py   # deve imprimir "OK"
```

## Convenções de Código

### Linguagem e estilo
- Python 3.9+ (walrus ok, match/case não — 3.10+)
- Sem formatter automático. Seguir o estilo existente: 4 espaços, ~100 cols
- Docstrings curtas em uma linha. Explicações maiores como comentários `# ponytail:`
- Comentários explicam o *porquê*, não o *o quê*

### Nomenclatura
| Elemento | Padrão | Exemplo |
|----------|--------|---------|
| Módulo | snake_case, nome curto | `inter_pdf.py`, `fmt.py` |
| Função pública | snake_case, verbo ou substantivo | `categoriza()`, `upsert()` |
| Helper interno | `_prefixo` | `_contraparte()` |
| Constantes | UPPER_SNAKE | `NAO_FLUXO`, `CATEGORIAS` |
| Variáveis SQL | snake_case | `movimentacoes`, `padrao` |

### Dependências
- **Proibido** adicionar dependências além de `pypdf` (ver SDD-002)
- Se precisar de algo da stdlib, verificar que existe no Python 3.9+
- Se for inevitável adicionar uma dep, criar SDD primeiro e justificar

### Sinal de valores
- Negativo = saída de dinheiro. Sempre. Sem exceção.
- Positivo = entrada de dinheiro.
- Nunca inverter a convenção "temporariamente" — quebra queries, dashboard, testes.

### IDs
- Devem ser determinísticos (hash do conteúdo) — ver SDD-004
- Formato: `<origem>_<hash_ou_id_externo>`
- Reimportar com o mesmo conteúdo NUNCA pode duplicar

### Categorização
- Keywords ficam em `store.CATEGORIAS` — ordem importa (primeira que casa ganha)
- Regras manuais ficam na tabela `regras` — padrão mais longo ganha
- `categoriza()` recebe `tipo + " " + descricao` — o tipo faz parte da busca
- Categoria nova = nome novo. Não precisa cadastrar em nenhum enum.

## Checklist de Mudança

Antes de commitar, verificar:

- [ ] `python test_fin.py` imprime "OK"
- [ ] Se adicionou/modificou ingestão: reimportar o mesmo arquivo não duplica?
- [ ] Se adicionou keyword/categoria: testou com `store.categoriza("...")` no test?
- [ ] Se mexeu no dash: a página renderiza sem `{` literal no HTML? (teste verifica)
- [ ] Se adicionou query: `NAO_FLUXO` está sendo respeitado onde deve?
- [ ] Se mudou schema: `store.conn()` cria/migra automaticamente?
- [ ] Se uma decisão nova ou uma mudança de decisão existente: criou/atualizou SDD?

## Estrutura de Arquivos

```
finance/
├── store.py          # Camada de dados (schema, upsert, categorização)
├── fmt.py            # Helpers de formatação BR (valor_br, brl, dia_br, etc.)
├── mp_sync.py        # Ingestão: Mercado Pago API
├── inter_pdf.py      # Ingestão: PDF do Inter (extrato + fatura)
├── inter_import.py   # Ingestão: CSV do Inter (legado)
├── cat.py            # CLI: categorização manual
├── dash.py           # Dashboard web (HTTP + HTML + queries)
├── creds.py          # Lê credenciais MP do ambiente ou de .env (nunca versionadas)
├── test_fin.py       # Testes (unitários + integração)
├── fin.db            # SQLite (gitignored em prod, versionado aqui pra conveniência)
├── ARCHITECTURE.md   # Visão geral do sistema
├── CONTRIBUTING.md   # Este arquivo
└── docs/decisions/   # SDDs (Software Design Decisions)
```

## Adicionando uma Nova Fonte de Dados

1. Criar `nova_fonte.py` na raiz
2. Gerar lista de tuples: `(id, origem, tipo, status, valor, descricao, data)`
3. ID deve ser `<origem>_<hash_deterministico>`
4. Chamar `store.upsert(c, rows)` — categorização é automática
5. Alterar CHECK constraint de `origem` em `store.conn()` se necessário
6. Adicionar testes em `test_fin.py`
7. Criar SDD se houver decisão não-óbvia

## Adicionando uma SDD

Arquivo: `docs/decisions/SDD-NNN-titulo-curto.md`

Estrutura:
```markdown
# SDD-NNN: Título

**Status**: Aceita | Proposta | Substituída por SDD-XXX
**Data**: YYYY-MM

## Decisão
O que foi decidido.

## Motivação
Por que essa escolha e não outra.

## Consequências
Positivas, negativas, trade-offs aceitos.

## Alternativas Descartadas
O que foi considerado e rejeitado, com motivo.
```

## Erros Comuns

- **Esqueceu `tipo` na categorização**: `categoriza(descricao)` vai errar para lançamentos
  do Inter onde o significado está no tipo. Sempre passe `f"{tipo} {descricao}"`.
- **Inverteu sinal no MP**: `collector_id == meu_id` → eu recebi → positivo. Caso contrário → negativo.
- **Duplicou contagem**: Fatura do cartão: ignorar linhas com `+` (pagamento). Investimento: não somar no gasto.
- **Placeholder `{...}` solto no HTML**: O teste verifica `"{" not in pagina.split("<style>")[0]`.
