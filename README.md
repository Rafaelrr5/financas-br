# finanças-br — tracking financeiro pessoal (Inter + Mercado Pago + B3)

Importa extrato de banco e de corretora brasileiros para um SQLite local,
categoriza os lançamentos e mostra tudo num dashboard web que roda na sua
máquina. Nada sai do computador: não há servidor, conta, nuvem nem telemetria.

Python 3.9+, **só stdlib** — exceto `pypdf`, usado apenas na importação de PDF,
que se instala sozinho no primeiro uso.

Fontes suportadas: **Banco Inter** (PDF de extrato e de fatura do cartão),
**Mercado Pago** (API de pagamentos) e **B3** (PDF de movimentação e de
posição). O banco é um `fin.db` local (troque o caminho com `FIN_DB`).

> Escrito para o ecossistema financeiro brasileiro: formato de valor
> (`1.234,56`), datas `dd/mm/aaaa` e o layout dos PDFs desses três emissores.
> A interface e o código são em português.

## Setup

```bash
git clone <este-repo> && cd financas-br
python test_fin.py          # valida a instalação -> "OK"
```

Para o Mercado Pago (opcional), copie `.env.example` para `.env` e preencha o
token. Sem token, tudo o mais continua funcionando.

```bash
cp .env.example .env
```

> **O `.env`, o banco `fin.db` e os PDFs de extrato nunca são versionados** —
> estão no `.gitignore`. São seus dados, não do repositório.

| Arquivo | O quê |
|---|---|
| `creds.py` | Lê as credenciais do Mercado Pago do ambiente ou de `.env` |
| `fmt.py` | Formatação brasileira (valor, data, mês) |
| `store.py` | Schema, upsert idempotente, categorização por palavra-chave |
| `mp_sync.py` | Puxa o Mercado Pago via `/v1/payments/search` (paginado) |
| `inter_pdf.py` | Importa PDF do Inter: extrato e fatura do cartão |
| `inter_import.py` | Importa CSV do Inter (legado — o Inter não exporta mais CSV) |
| `b3_pdf.py` | Importa PDF de movimentação da B3 |
| `b3_posicao.py` | Importa PDF de posição da B3 |
| `cat.py` | Categorização manual: cria regras e recategoriza |
| `dash.py` | Dashboard web local (`http.server`) |
| `test_fin.py` | Self-check: parser BR, categorias, idempotência |

### 1. Mercado Pago

```bash
python mp_sync.py        # últimos 30 dias
python mp_sync.py 90     # últimos 90 dias
```

O token de produção sai de `mercadopago.com.br/developers` → Suas integrações →
Credenciais de produção. Ele dá acesso de leitura ao histórico de pagamentos da
conta: trate como senha. Fica em `.env` (ignorado pelo git) ou na variável de
ambiente `MP_ACCESS_TOKEN` — nunca no código.

**Agendar semanal (Windows):**
```powershell
schtasks /create /tn "MP Sync" /tr "python C:\caminho\para\financas-br\mp_sync.py 14" /sc weekly /d SUN /st 08:00
```
**Cron (Linux/macOS):** `0 8 * * 0 /usr/bin/python3 /caminho/mp_sync.py 14`

O `.env` existe justamente para isso: tarefa agendada não herda variável de
ambiente com facilidade no Windows.

### 2. Inter — exportar PDF

O Inter só exporta PDF hoje. Extrato e fatura do cartão usam o mesmo comando (o
tipo é detectado pelo conteúdo):

1. App/Internet Banking → **Extrato** (período) ou **Cartão → Faturas** →
   exportar **PDF**.
2. Importar:

```bash
python inter_pdf.py Extrato-01-08-2026-a-01-09-2026.pdf fatura-inter-2026-07.pdf
```

Reimportar o mesmo arquivo (ou períodos sobrepostos) **não duplica**: o ID é
`sha256` de `data|tipo|descrição|valor` + nº da repetição no arquivo.

**Fatura:** linhas com `+` (pagamento da fatura, estorno) são ignoradas — a
saída já aparece no extrato da conta e contaria em dobro. Parcelas entram com a
data da compra original, como no PDF. `tipo` = `cartao <número mascarado>`.

### 3. B3

```bash
python b3_pdf.py movimentacao-2026-08-04.pdf     # movimentações -> tabela b3_mov
python b3_posicao.py posicao-2026-09-01.pdf      # posição -> tabela posicao
```

### 4. Categorização manual

Palavra-chave automática não pega nome de estabelecimento. Para esses, uma
**regra**: um trecho da descrição → categoria. Vale retroativo **e** nas
próximas importações. **Categoria nova é só um nome novo** — nada a cadastrar.

```bash
python cat.py                        # fila: o que está em 'outros', maior valor primeiro
python cat.py "pingo no i" lazer     # cria a regra e recategoriza tudo
python cat.py --list                 # regras atuais
python cat.py --rm "pingo no i"      # remove a regra (e recategoriza)
```

No dashboard dá no mesmo, e mais rápido: a seção **Triar** lista o que está em
`outros` (maior valor primeiro) com um campo de categoria por linha.

Regras ficam na tabela `regras` (`padrao` normalizado sem acento → `categoria`),
vencem as palavras-chave fixas de `store.CATEGORIAS`, e entre si o **padrão mais
longo ganha** (`padaria do zé` antes de `padaria`).

### 5. Dashboard

```bash
python dash.py     # http://localhost:8000
```

Faz o processo inteiro pelo navegador, sem CLI. Uma página, seções separadas por
dobra:

| Seção | O quê |
|---|---|
| **Fontes** | Importar PDF do Inter e da B3, sincronizar Mercado Pago por nº de dias |
| **Período** | Atalhos 7d/30d/…/tudo + filtros de data, origem, tipo e categoria |
| **Resumo** | Fechamento (gasto, entrada, régua, líquido), barras dos 12 últimos meses, gasto/dia |
| **Parcelado** | Compras parceladas: quanto falta, quantas parcelas, em que mês cada uma cai |
| **Triar** | Fila do `outros` com um campo de categoria por linha → vira regra na hora |
| **Onde** | Gasto por categoria e os 15 maiores estabelecimentos |
| **Razão** | 500 lançamentos mais recentes, agrupados por dia, com o acumulado na margem |

**Duas tintas.** Vermelho é saída de dinheiro e nada mais; entrada é preta,
distinguida por barra vazada em vez de cor (sobrevive a daltonismo); azul é o
que você escreveu — regra, filtro ativo, carimbo. Segue o tema claro/escuro do
sistema.

**"Acum"** no razão é o acumulado das linhas exibidas, da mais antiga para a
mais nova. **Não é o saldo da conta.** **Líquido** é entrada − gasto na janela
filtrada, não patrimônio.

**Parcelado** não segue o filtro de período: é compromisso futuro, não
histórico. O cronograma é *deduzido* — o extrato lança toda parcela com a data
da compra original e não diz em qual fatura cada uma cai, então a seção assume
uma parcela por mês a partir da primeira fatura depois da compra (fechamento dia
15, `store.FECHAMENTO`). Valor marcado com `*` é estimado.

## Segurança

O dashboard **escuta só em `127.0.0.1` e não tem autenticação** — o isolamento
*é* a rede loopback. Ele mostra seu extrato inteiro, então:

- mudar `FIN_HOST` para `0.0.0.0` entrega o histórico financeiro a qualquer um
  que alcance a porta. O programa avisa no terminal quando você faz isso;
- `POST /regra` grava no banco e não tem token CSRF: outra aba do navegador
  poderia disparar. O impacto máximo é uma regra de categoria errada, revertível
  com `cat.py --rm`;
- credenciais só no ambiente ou em `.env`, nunca no código (`docs/decisions/SDD-001`).

## Convenções

- **Sinal**: negativo = saída, positivo = entrada.
- **Categorias**: dict `store.CATEGORIAS` (acento-insensível), casado contra
  `tipo + descrição` — no extrato Inter o sentido está no tipo ("Debito Tesouro
  Direto"), não na descrição. A primeira categoria que casa ganha, então a ordem
  do dict importa.
- `investimento` (B3, Tesouro, CDB, proventos), `fatura` (pagamento do cartão) e
  `salario` não são gasto de consumo: filtre no dashboard antes de olhar "quanto
  gastei".
- Fora de escopo por decisão: Open Finance regulado, scraping, agregadores pagos.

## Documentação

| Documento | Conteúdo |
|---|---|
| `ARCHITECTURE.md` | Camadas, fluxo de dados, invariantes, schema |
| `CONTRIBUTING.md` | Convenções de código, nomenclatura, checklist de mudança |
| `docs/decisions/` | SDDs — registro das decisões de projeto e do porquê |

## Limitações conhecidas

- **Três emissores, e só.** Inter, Mercado Pago e B3. Outro banco precisa de um
  parser novo — é o tipo de contribuição mais útil aqui.
- **PDF é layout, não formato de dados.** Se o Inter ou a B3 mudarem o desenho
  do extrato, o regex quebra. O import aborta com "nenhuma movimentação
  encontrada" em vez de importar vazio, mas confira o total contra o PDF de vez
  em quando.
- **Mercado Pago sem OAuth**, só conta própria. Se você **recebe** pagamentos
  pelo MP, revise a regra de sinal em `mp_sync.to_row`.
- **Sem multiusuário, sem login, sem sincronização.** Um banco, uma máquina.
- **O saldo da conta não é guardado** — o parser lê lançamentos, não saldo, e a
  coluna "Acum" é acumulado das linhas exibidas.
- **Categorização é palavra-chave**, não modelo. Erra em estabelecimento com
  nome genérico; a seção Triar existe por causa disso.

Boas primeiras contribuições: um parser para outro banco brasileiro (Nubank,
Itaú, Caixa), mais palavras-chave em `store.CATEGORIAS`, e exportação CSV/OFX.

## Licença

[MIT](./LICENSE).
