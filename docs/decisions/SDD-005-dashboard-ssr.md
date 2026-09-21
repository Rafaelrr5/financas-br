# SDD-005: Dashboard Server-Side Rendered

**Status**: Aceita  
**Data**: 2025-07  
**Contexto**: Dashboard local para visualização e categorização.

## Decisão

O dashboard é uma única página HTML renderizada inteiramente no servidor (`dash.py`).
O JavaScript (`<script>` inline) faz apenas:
- `fetch` + `replaceWith` para evitar reload completo em POSTs
- Dropdown pesquisável para o campo de categoria
- Preservação do estado de `<details>` abertos após troca

Não há API JSON, não há SPA, não há bundler.

## Motivação

- Uma página, um arquivo Python, zero toolchain frontend.
- O servidor já tem os dados em memória (query feita no render): serializar pra JSON e deserializar no client seria trabalho duplicado.
- Sem framework JS: a página funciona 100% sem JS (forms nativos + redirect 303).
- Manutenção: qualquer mudança é editar um string Python com placeholders `{...}`.

## Consequências

- **Positivas**: Zero build step, zero node_modules, funciona offline, tempo de resposta <50ms.
- **Negativas**: HTML inline num arquivo de 38KB é desconfortável de editar; sem hot reload.
- **Trade-off**: Prioridade é simplicidade operacional sobre DX de frontend.

## Alternativas Descartadas

- React/Vue SPA + API JSON: overkill para 1 usuário, adiciona node/npm/build.
- Jinja2/Mako templates: adiciona dependência; string.format() já resolve.
- HTMX: elegante mas é mais uma dependência CDN e muda a arquitetura mental.
