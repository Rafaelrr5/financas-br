# SDD-007: NAO_FLUXO — Investimentos e Fatura Fora do Razão de Consumo

**Status**: Aceita  
**Data**: 2025-07  
**Contexto**: Investimentos e pagamento de fatura distorcem a visão de "quanto gastei".

## Decisão

Categorias em `store.NAO_FLUXO` (`aplicacao`, `resgate`, `rendimento`, `fatura`, `interno`)
são excluídas do cálculo de gasto/entrada e do razão principal. Investimentos têm
seção dedicada no dashboard.

## Motivação

- **Investimento** (aplicação/resgate/rendimento): é remanejo de patrimônio, não consumo.
  Debitar R$500 no Tesouro Direto não é "gastar R$500".
- **Fatura**: pagamento do cartão já aparece como compras individuais no extrato da fatura.
  Contar o pagamento seria dobrar o valor.
- **Interno**: Pix entre contas próprias (ex.: Inter → Nubank) não é gasto nem entrada real.

## Implementação

```python
NAO_FLUXO = ("aplicacao", "resgate", "rendimento", "fatura", "interno")
INVESTIMENTO_CATS = ("aplicacao", "resgate", "rendimento")
```

- Queries de gasto/entrada: `WHERE categoria NOT IN (NAO_FLUXO)`
- Razão: exclui `INVESTIMENTO_CATS` (investimentos têm seção própria)
- Acumulado no razão: soma só o que é fluxo de consumo

## Consequências

- **Positivas**: "Quanto gastei no mês" reflete consumo real; investimentos separados.
- **Negativas**: O acumulado no razão não é "saldo da conta" — é fluxo de consumo.
  README e hint no dash explicam isso.

## Alternativas Descartadas

- Incluir tudo e filtrar no dashboard: confuso, o default estaria errado.
- Duas tabelas (consumo vs patrimônio): complexidade de schema desnecessária.
