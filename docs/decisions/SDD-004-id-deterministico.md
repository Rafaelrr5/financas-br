# SDD-004: ID Determinístico por Hash

**Status**: Aceita  
**Data**: 2025-07  
**Contexto**: Usuário reimporta o mesmo PDF ou sincroniza MP com períodos sobrepostos.

## Decisão

O ID de cada movimentação é gerado deterministicamente a partir do conteúdo:
- **Mercado Pago**: `mp_<payment_id>` (já é único na API)
- **Inter PDF**: `inter_<sha256(data|tipo|descricao|valor|nº_repetição)[:16]>`
- **Inter CSV**: `inter_<sha256(linha_bruta)[:16]>`

## Motivação

- **Idempotência grátis**: `INSERT … ON CONFLICT(id) DO UPDATE` garante que reimportar não duplica.
- **Estabilidade**: o mesmo PDF sempre gera os mesmos IDs, em qualquer ordem de importação.
- **Sem sequence/autoincrement**: evita problemas de gap e não depende de estado do banco.

## Tratamento de Duplicatas Reais

Um mesmo lançamento pode aparecer 2x no mesmo dia (duas compras iguais no mesmo lugar).
O `nº_repetição` (Counter por chave no arquivo) distingue essas linhas mantendo
estabilidade entre importações.

## Consequências

- **Positivas**: Reimportar é seguro; sync sobreposto é seguro; não precisa de "limpar antes de importar".
- **Negativas**: Se o PDF mudar layout (reordenar linhas), os IDs mudam e o banco terá linhas "orfãs" + novas. Na prática nunca aconteceu.
- **Mitigação**: O import aborta se não encontrar nenhuma movimentação — detecta mudança de layout.

## Alternativas Descartadas

- UUID aleatório: perde idempotência.
- Autoincrement: perde estabilidade entre reimportações.
- Hash só de valor+data: colide quando a mesma compra aparece 2x no dia.
