# Política de Segurança

## Como reportar uma vulnerabilidade

**Não abra uma issue pública** para relatar problemas de segurança.

Use o reporte privado do GitHub: na página do repositório, vá em **Security → Report a vulnerability**. O relato fica visível apenas para os mantenedores.

Inclua, se possível:

- descrição do problema e do impacto;
- passos para reproduzir;
- versão ou commit afetado.

Responderemos assim que possível. Como este é um projeto mantido nas horas vagas, não há prazo garantido, mas relatos de segurança têm prioridade.

## Versões suportadas

Apenas a versão mais recente da branch principal recebe correções.

## Padrões de segurança

O AutoDoc vem **seguro por padrão**. Antes de expor uma instância fora da sua máquina, confira:

| Configuração | Padrão | Observação |
|---|---|---|
| `APP_ENV` | `production` | Em produção, a API **não sobe** se o `JWT_SECRET` for o valor de exemplo ou tiver menos de 32 caracteres. Use `development` apenas localmente. |
| `JWT_SECRET` | — | Gere um valor aleatório: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SEED_DEMO_USER` | `false` | Nunca ative em uma instância exposta. |
| `ALLOW_REGISTRATION` | `false` | Crie usuários com `python -m app.scripts.create_user --email ...`. |
| `ALLOW_SERVER_GITHUB_TOKEN` | `false` | Com `true`, o `GITHUB_TOKEN` do servidor é usado em nome de **qualquer** usuário logado, que passa a acessar os repositórios privados desse token. |
| `TESTGEN_EXECUTION` | `none` | O agente gerador de testes **executa código gerado por IA**. `docker` roda em contêiner isolado (sem rede, com limite de memória e CPU); `local` roda direto na máquina e só deve ser usado em ambiente de desenvolvimento confiável. |
| `CORS_ORIGINS` | `http://localhost:4200` | Restrinja aos domínios do seu frontend. |

## Cuidados adicionais

- **Código enviado à IA:** o conteúdo documentado é enviado ao provedor de IA configurado (OpenAI, Anthropic ou o endereço em `OPENAI_COMPATIBLE_BASE_URL`). Não use o AutoDoc com código que não pode sair da sua infraestrutura, a menos que o provedor seja local (por exemplo, Ollama ou LM Studio na mesma máquina ou rede).
- **Servidor MCP em modo SSE:** não tem autenticação própria e escuta em `127.0.0.1` por padrão. Não exponha a porta em rede pública.
- **Docker Compose (`infra/`):** é destinado a desenvolvimento. Para produção, use HTTPS, senhas fortes e não publique as portas do Postgres e do Redis.
- **Segredos:** nunca commite o arquivo `.env`. Use os arquivos `.env.example` como modelo.
