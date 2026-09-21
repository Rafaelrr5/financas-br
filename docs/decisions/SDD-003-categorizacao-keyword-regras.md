# SDD-003: Categorização por Keyword + Regras Manuais

**Status**: Aceita  
**Data**: 2025-07  
**Contexto**: Precisamos classificar ~1000 lançamentos/mês com esforço mínimo.

## Decisão

Categorização em duas camadas:
1. **Regras manuais** (tabela `regras`): substring normalizada → categoria. Padrão mais longo ganha.
2. **Keywords fixas** (dict `store.CATEGORIAS`): primeira categoria que casar ganha.
Fallback: `"outros"`.

Regra manual sempre vence keyword fixa. Categorização é refeita do zero (`recategoriza()`)
quando uma regra muda, garantindo retroatividade.

## Motivação

- Keywords cobrem ~80% dos lançamentos automaticamente (supermercado, farmácia, transporte...).
- Os 20% restantes são nomes de estabelecimentos que não seguem padrão ("SandraReginaDe", "PINGO NO I") — regra manual resolve com 1 comando.
- Retroatividade: corrigir uma regra corrige todo o histórico, sem reimportar.
- Categoria nova = nome novo. Sem cadastro prévio, sem enum fechado.

## Mecanismo

```
categoriza(tipo + " " + descricao, regras) ->
  1. Para cada regra (do padrão mais longo ao mais curto):
     se padrão ⊆ normaliza(texto): retorna categoria da regra
  2. Para cada keyword em CATEGORIAS (ordem do dict):
     se keyword ⊆ normaliza(texto): retorna categoria
  3. retorna "outros"
```

- `normaliza()`: minúsculo + remove acentos (NFD + strip Mn)
- Tipo entra na busca porque no Inter o significado está nele ("Debito Tesouro Direto")

## Consequências

- **Positivas**: Determinístico, auditável, rápido, sem modelo de ML.
- **Negativas**: Nomes novos caem em "outros" até criar regra; a fila de triagem resolve isso.
- **Trade-off**: Mais esforço manual que ML, mas zero falso positivo e zero caixa-preta.

## Alternativas Descartadas

- ML/LLM para classificar: latência, custo, imprevisibilidade, e treinar com ~500 amostras não dá boa acurácia.
- Regex completo por lançamento: overkill — substring simples já resolve 95%.
- Categorização imutável (sem retroativo): o usuário teria que reimportar para corrigir.
