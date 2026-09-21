# SDD-001: Credenciais fora do código

**Status**: Aceita (substitui a decisão anterior de hardcoding)
**Contexto**: O projeto é de uso pessoal e roda localmente, mas o código é
público.

## Decisão

Nenhuma credencial fica no código. `creds.py` resolve os valores em duas
etapas, a primeira que existir ganha:

1. variável de ambiente (`MP_ACCESS_TOKEN`);
2. arquivo `.env` ao lado do código, listado no `.gitignore`.

`.env.example` documenta todas as variáveis e o que cada uma dá acesso.

## Motivação

- Código público não pode carregar segredo, ponto. Um token no repositório
  está comprometido no instante em que o repositório existe.
- O arquivo `.env` resolve o motivo original do hardcoding: o Agendador de
  Tarefas do Windows não herda variáveis de ambiente com facilidade, então
  `python mp_sync.py` agendado continua funcionando sem configurar o sistema.
- Sem dependência nova: o leitor de `.env` são vinte linhas de stdlib, não
  `python-dotenv` (mantém SDD-002).

## Consequências

- **Positivas**: nada de segredo em commit; o mesmo código serve para quem
  clonar; a mensagem de erro diz exatamente o que configurar.
- **Negativas**: existe um passo de setup que antes não existia — copiar
  `.env.example` para `.env`.
- **Degradação limpa**: sem token, apenas o Mercado Pago para. Importação de
  PDF do Inter e da B3, categorização e dashboard seguem funcionando.

## Alternativas descartadas

- `python-dotenv`: dependência externa para o que vinte linhas de stdlib
  resolvem.
- Keyring do sistema operacional: complexidade desproporcional e quebra o uso
  agendado sem sessão interativa.
- Manter hardcoded e só avisar no README: inaceitável em repositório público.
