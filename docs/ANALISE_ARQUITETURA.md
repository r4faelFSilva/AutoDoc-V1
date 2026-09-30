# Análise de Arquitetura — AutoDoc → Extensão VS Code + App Desktop (Tauri)

> Data da análise: 2026-09-30 · Branch analisada: `desenvolvimento` (commit `365d47a`)
> Escopo: leitura do código, sem nenhuma modificação. As estimativas de esforço são para um desenvolvedor que já conhece o código e devem ser tratadas como ordem de grandeza.

## Resumo

- **Stack atual:** o backend é Python (FastAPI + SQLAlchemy + SQLite + SDK `openai`) e o frontend é Angular 21 standalone (Material, ngx-markdown). A IA é chamada de forma síncrona pelo SDK oficial da OpenAI, com uma chave global no `.env`.
- **Núcleo aproveitável:** cerca de 1.000 das ~1.600 linhas de `backend/app/services/` são lógica de negócio (prompts, montagem do contexto do repositório, avaliação de necessidade de atualização, marcador AutoDoc, geração de template a partir de exemplo, commit no GitHub). Essa lógica está misturada com três coisas que precisam sair: a `Session` do SQLAlchemy, os DTOs Pydantic da API e o `settings` global.
- **O obstáculo principal é a linguagem, não o acoplamento.** Uma extensão VS Code roda em Node.js. Manter o núcleo em Python obriga a embarcar um executável Python (sidecar) em cada plataforma.
- **Recomendação:** portar o núcleo para **TypeScript** (`@autodoc/core`) e usá-lo diretamente na extensão (host Node) e no Tauri (webview + plugins). Antes do porte, vale criar testes de caracterização e testar o Ollama no Python atual, que é barato e elimina o maior risco (a qualidade dos modelos locais).
- **Esforço total estimado** (núcleo TS + extensão MVP + app Tauri): **~6 a 9 semanas-pessoa**. Veja a seção 6.

---

## 1. Stack atual

### 1.1 Visão geral

```text
[Angular 21 SPA :4200] --/api (proxy dev)--> [FastAPI :8000] --> SQLite (backend/data/autodoc.db)
                                                   |--> OpenAI Chat Completions (SDK openai, síncrono)
                                                   |--> GitHub REST API (httpx: tarball, commits, contents)
[Azure Pipelines] --HTTP + JWT--> [FastAPI]   (avaliar → gerar → commitar)
```

> Atenção: o `README.md` atual foi gerado pelo próprio AutoDoc e está **incorreto**. Ele cita Node.js/Express/MongoDB, mas o projeto é FastAPI/SQLite. Isso não afeta esta análise, mas mostra um problema de qualidade da geração (ver 5.4).

### 1.2 Backend (`backend/`)

| Item | Detalhe |
|------|---------|
| Linguagem | Python 3.10+ (usa `str \| None`, `removeprefix`) |
| Framework HTTP | FastAPI + Uvicorn. Rotas em [app/api/routers/](backend/app/api/routers/) (`auth`, `templates`, `documentation`) |
| Configuração | `pydantic-settings`: um objeto global `settings` lido de `.env` ([config.py](backend/app/config.py)) |
| Autenticação | E-mail/senha com `bcrypt` e JWT HS256 (`python-jose`). O seed cria o usuário `demo@autodoc.dev` / `demo` |
| HTTP externo | `httpx` síncrono para a API do GitHub |
| IA | SDK `openai>=1.55` ([ai_openai.py](backend/app/services/ai_openai.py)) |
| Testes | **Nenhum** |
| Migrações | **Nenhuma**. O schema é criado com `Base.metadata.create_all` no import de `main.py` |

### 1.3 Como o SQLite é usado

- É acessado pelo ORM SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`), com `check_same_thread=False` e o arquivo padrão em `backend/data/autodoc.db`. O `.db` **está versionado no git**.
- Há três tabelas:
  - `users`: id, email, hashed_password.
  - `templates`: nome, descrição, `content` (é o prompt do template) e `type` (technical/functional). A tabela é **global**, sem `user_id`, e qualquer usuário autenticado pode editar ou apagar os templates.
  - `documentation_records`: markdown gerado, filename, template, status, `github_url`, `source`, `user_id`.
- Não há SQL específico de SQLite. A busca usa `ILIKE '%termo%'`, sem FTS. Isso facilita a troca do armazenamento.
- Uma geração com falha também é gravada, com `status="failed"` e `content="# Erro na geração ..."`.

### 1.4 Como a API da OpenAI é chamada

Em [ai_openai.py](backend/app/services/ai_openai.py) há duas funções quase idênticas:

| Função | Uso | Parâmetros |
|--------|-----|------------|
| `generate_markdown` | Gerar a documentação | `chat.completions.create`, `temperature=0.3`, sem streaming |
| `generate_json` | Avaliar se a doc precisa ser atualizada; gerar template a partir de exemplo | `response_format={"type":"json_object"}`, `temperature=0.2`, `max_completion_tokens` opcional |

- Um cliente `OpenAI(...)` novo é criado a cada chamada, com a chave e o modelo vindos de `settings` (`OPENAI_API_KEY`, `OPENAI_MODEL=gpt-4o-mini`).
- Os timeouts são de 120 s, ou 180 s na geração de template. A requisição HTTP do front fica bloqueada até a IA responder.
- Todos os erros viram `AIServiceError(str(e))`, sem distinção entre falta de crédito, rate limit, timeout ou contexto excedido.
- O contexto enviado pode ser grande. O modo GitHub monta até **120.000 caracteres** (80 arquivos, com no máximo 12.000 caracteres por arquivo) em [github_archive.py](backend/app/services/github_archive.py), o que dá cerca de 30 a 40 mil tokens. Isso importa para o Ollama (seção 5).

### 1.5 Frontend (`frontend/`)

| Item | Detalhe |
|------|---------|
| Framework | Angular 21 com componentes standalone, signals e rotas lazy |
| UI | Angular Material (snackbar), `lucide-angular`, SCSS próprio, `particle-background` decorativo |
| Markdown | `ngx-markdown` + `marked` + `highlight.js` |
| HTTP | `HttpClient` + `jwtInterceptor`, com base `'/api'` fixa em 3 serviços e proxy para `127.0.0.1:8000` em dev |
| Estado de auth | JWT em `localStorage` (`autodoc_token`) |
| Telas | login, register, dashboard, generate, templates, history, viewer (edição, busca com destaque), search |
| Exportação | `.md` via `Blob` + `<a download>`, PDF via iframe + `window.print()`, cópia via `navigator.clipboard` |

### 1.6 CI

[azure-pipelines.yml](azure-pipelines.yml) é um **cliente HTTP** da API, com os passos login → `/generate/github/evaluate` → `/generate/github` → `/generate/github/commit`. Os endpoints `evaluate` e `sync` **só são usados pelo pipeline**, não pelo frontend. Isso mostra que já existe um segundo consumidor "sem interface", o que é um bom sinal para a extração do núcleo.

---

## 2. Lógica de negócio × acoplamento à interface

### 2.1 Classificação por arquivo

| Arquivo | Tipo | Portabilidade | Observação |
|---------|------|---------------|------------|
| [autodoc_marker.py](backend/app/services/autodoc_marker.py) | Regra pura | Alta | Marcador `<!-- autodoc:generated -->` e heurística de documentação "substancial" |
| [documentation_evaluator.py](backend/app/services/documentation_evaluator.py) | Regra pura + prompt + IA | Alta | Árvore de decisão (bootstrap/skipped/maintenance) antes de chamar a IA. É o ativo mais valioso |
| [template_ai_skeleton.py](backend/app/services/template_ai_skeleton.py) | Prompt + IA + pós-processamento | Alta | Truncamento, extração do índice, remoção de nomes próprios, parse de JSON tolerante |
| [github_archive.py](backend/app/services/github_archive.py) | I/O de rede + filtro de arquivos | Média | Faz download do tarball, extrai em diretório temporário, prioriza e trunca arquivos. Usa `settings.github_token` global |
| [github_changes.py](backend/app/services/github_changes.py) | I/O de rede + regra | Alta | Busca o último commit, os arquivos alterados e o conteúdo da doc. O token é injetado por parâmetro |
| [github_commit.py](backend/app/services/github_commit.py) | I/O de rede + regra | Alta | Contents API com detecção de conteúdo idêntico. O token é injetado |
| [ai_openai.py](backend/app/services/ai_openai.py) | Adaptador de IA | Reescrever | É um único provedor com config global. Vira a interface `LLMProvider` |
| [documentation_service.py](backend/app/services/documentation_service.py) | **Misturado** | Separar | O pipeline de geração (prompt, IA) está junto de persistência (`Session`), DTOs de resposta, busca e estatísticas |
| [template_service.py](backend/app/services/template_service.py) | CRUD | Substituir | É um repositório; vira interface de armazenamento |
| [auth_service.py](backend/app/services/auth_service.py), [dependencies.py](backend/app/dependencies.py) | Infra web | Descartar no local | Login e JWT não fazem sentido num app de um usuário só |
| [seed.py](backend/app/services/seed.py) | Dados | Converter | Os 3 templates padrão viram um JSON/Markdown embarcado |
| `models/`, `schemas/`, `routers/`, `main.py`, `config.py`, `database.py` | Infra web/ORM | Ficam só no backend web | — |

### 2.2 Acoplamentos concretos que precisam ser desfeitos

1. **`settings` global importado dentro dos serviços** (`ai_openai`, `github_archive`, `auth_service`). Chave, modelo e token precisam virar parâmetros ou configuração injetada.
2. **Serviços recebem `Session` e devolvem DTOs da API.** Por exemplo, `generate_from_code` monta o prompt, chama a IA, grava no banco e devolve `DocumentationRecordResponse`, tudo junto. Isso deve virar:
   - `generateDocumentation(input, template, provider) → { markdown, status }`, que é puro e testável;
   - a persistência, que fica a cargo do chamador (backend, extensão ou Tauri).
3. **Controle de fluxo por string de exceção.** `GitHubCommitError("SKIP_UNCHANGED: ...")` é interpretado por `startswith` em dois lugares, e `ValueError` com texto chega ao usuário como mensagem HTTP. É preciso usar resultados tipados, como `{ kind: "unchanged" }`.
4. **Regra de negócio dentro do router.** Em `documentation.py`, `source` é decidido comparando `filename != "código-colado.txt"`, uma string que vem do frontend.
5. **Multiusuário implícito.** `user_id` aparece em todas as consultas. Localmente existe um único usuário, então isso vira um "workspace" ou desaparece.
6. **Efeitos colaterais no import.** `main.py` cria as tabelas e roda o seed ao ser importado, e `database.py` cria o diretório no import.
7. **Inconsistência de token GitHub.** O modo geração (`github_archive`) usa só o `GITHUB_TOKEN` do servidor. Já avaliação e commit usam o token do request. Um repositório privado pode ser commitado mas não lido pelo token do usuário. Vale corrigir no porte.

### 2.3 Frontend: o que é reaproveitável

- **Não há lógica de negócio relevante no Angular.** Há apenas validação de URL do GitHub, convenções de nome de arquivo (`-doc.md`) e o layout do PDF.
- **O ponto de costura já existe.** Os três serviços (`AuthService`, `DocumentationService`, `TemplateService`) concentram 100% das chamadas HTTP. Trocar esses serviços por uma interface (`InjectionToken<AutoDocBackend>`) com implementações "HTTP" e "local" permite reaproveitar todas as telas no Tauri.
- **APIs de navegador que quebram fora do navegador** (29 usos de `localStorage`, `window.*` e `document.*`):

| Uso | Onde | Problema no VS Code webview | Problema no Tauri |
|-----|------|-----------------------------|-------------------|
| `'/api'` relativo + proxy | serviços | Não há servidor | Não há servidor |
| `<a download>` com Blob | generate, viewer | Não funciona | Não confiável; usar `plugin-dialog` + `plugin-fs` |
| `window.print()` em iframe | pdf-export | Indisponível | Funciona no WebView2 (Windows); **validar** no macOS/Linux |
| `navigator.clipboard` | generate, viewer | Restrito; usar `vscode.env.clipboard` | OK, ou `plugin-clipboard-manager` |
| `window.open(url)` | generate | Usar `vscode.env.openExternal` | Usar `plugin-opener` |
| `localStorage` (JWT) | auth | Some com a autenticação | Some com a autenticação |
| Rotas `path` (HTML5) | app.routes | Usar `withHashLocation()` | Funciona, mas hash é mais simples |

---

## 3. Esforço para extrair o núcleo

### 3.1 Decisão central: em que linguagem fica o núcleo?

| Opção | Como roda no VS Code | Como roda no Tauri | Reaproveitamento | Riscos |
|-------|---------------------|--------------------|------------------|--------|
| **A. Manter Python (sidecar)** | A extensão sobe um executável PyInstaller do FastAPI em `localhost` | Sidecar do Tauri (`externalBin`) | ~100% do backend | VSIX por plataforma (win/mac-arm/mac-x64/linux) com 30 a 60 MB cada; **falso positivo de antivírus com PyInstaller em ambiente corporativo**; gestão de porta e ciclo de vida do processo; servidor local exposto a outros processos (exige token aleatório); inicialização de 1 a 3 s |
| **B. Portar para TypeScript** ✅ | Import direto no extension host (Node) | Import direto no webview, com rede via `tauri-plugin-http` | Regras, prompts e heurísticas são reescritos 1:1 (~1.000 linhas); Angular reaproveitado no Tauri | Custo do porte; duas implementações enquanto o backend web continuar em Python |
| C. Backend remoto (hospedado) | A extensão é um cliente HTTP | O app é um cliente HTTP | ~100% | Exige hospedagem; o código do usuário e a chave dele transitam pelo seu servidor; **não combina com Ollama local** |
| D. Núcleo em Rust | Só via WASM, o que é complexo | Nativo | Baixo | Reescrita total numa linguagem nova para a equipe; nenhuma vantagem para a extensão |

**Recomendação: B.** O núcleo é dominado por montagem de strings (prompts), chamadas HTTP e regras simples, e nada disso depende de bibliotecas Python. O porte é mecânico. A opção A aproveita mais código, mas cobra caro em distribuição, e esse custo se repete a cada release e em cada máquina corporativa.

### 3.2 O que reescrever ou adaptar (opção B)

Estrutura proposta:

```text
packages/
  core/                      ← TypeScript puro, sem dependência de vscode/tauri/angular
    providers/               LLMProvider + openai, ollama, anthropic, openai-compatible
    prompts/                 *.md com os system prompts (fonte única, ver 3.3)
    pipeline/                generateDocumentation, evaluateDocUpdate, templateFromExample
    github/                  client (fetch injetável), repoBundle, changes, commit
    source/                  SourceCollector: LocalFsCollector | GithubTarballCollector
    marker.ts
    storage.ts               interfaces TemplateRepo, HistoryRepo (sem implementação)
    defaults/templates.json  seed
  vscode-extension/          adapters: SecretStorage, workspace.fs, GitHub auth, arquivos
  desktop-tauri/             Angular + AutoDocBackend local + tauri-plugin-sql/http/…
backend/ (Python)            continua servindo web + Azure Pipelines
```

| Componente | Ação | Esforço |
|------------|------|---------|
| Testes de caracterização no Python (prompts gerados, decisões do avaliador, pós-processamento do template) | Novo; serve de oráculo para o porte | 2 a 3 d |
| `LLMProvider` + OpenAI + Ollama + compatível com OpenAI (+ Anthropic opcional) | Novo | 3 a 4 d |
| `marker`, `evaluator`, `template_ai_skeleton` | Porte 1:1 | 2 a 3 d |
| `github_changes`, `github_commit` | Porte com `fetch` injetável | 2 d |
| `github_archive` → `SourceCollector` | Reescrever: usar zipball + `fflate` (JS puro) sem disco, e adicionar coletor do filesystem local | 2 a 3 d |
| `documentation_service` → `pipeline/generate` | Separar geração de persistência | 1 a 2 d |
| Interfaces de armazenamento + adaptador em memória para testes | Novo | 1 d |
| **Subtotal do núcleo** | | **~13 a 18 d** |

Não é preciso reescrever o seguinte:

- as telas Angular (para o Tauri);
- o backend Python (continua atendendo web e CI);
- o pipeline Azure.

### 3.3 Mitigar a duplicação Python × TypeScript

- Tirar os prompts do código Python para arquivos `.md`/`.json` em `packages/core/prompts/`, lidos pelas **duas** implementações. É onde mora o "comportamento" do produto.
- Usar os mesmos casos de teste (entrada → prompt esperado / decisão esperada) em JSON, executados por `pytest` e `vitest`.
- A longo prazo, se o web continuar, avaliar trocar o backend Python por um servidor Node fino (Fastify) sobre `@autodoc/core`, eliminando a duplicação. Isso é opcional e pode ser decidido depois.

---

## 4. Dependências problemáticas numa extensão VS Code

| Tema | Situação atual | Problema na extensão | Solução |
|------|----------------|----------------------|---------|
| **SQLite** | SQLAlchemy + arquivo `.db` | `better-sqlite3` e `sqlite3` são **módulos nativos**: exigem binário por plataforma **e** compilação para o ABI do Electron do VS Code, que muda entre versões. `node:sqlite` depende da versão do Node embutida no VS Code e ainda é experimental | **Não usar SQLite na extensão.** Guardar templates em `.autodoc/templates/*.md` no workspace (versionáveis e compartilháveis com o time) ou em `globalStorageUri`; o histórico vira arquivos `.md` + índice JSON em `globalStorageUri`. Se precisar mesmo de SQL, usar `sql.js` (WASM, sem binário nativo) |
| **bcrypt / JWT** | Auth local | `bcrypt` é nativo; e não há usuários | Remover. Não há login na extensão |
| **Extração de tar** | `tarfile` + disco temporário | — | No modo "workspace local" não é necessária: ler via `vscode.workspace.fs` respeitando `.gitignore` (`workspace.findFiles` com exclude). Para URLs do GitHub, usar zipball + `fflate` |
| **Acesso a arquivos** | Upload pelo navegador | Na extensão isso é uma vantagem, não um problema | `workspace.fs` funciona também em Remote/WSL/Codespaces; não usar `fs` do Node direto se quiser suportar ambientes remotos |
| **CORS** | FastAPI libera `localhost:4200` | O **extension host** (Node) não tem CORS: chamadas à OpenAI, Ollama e GitHub funcionam direto. **Webviews** têm CSP e CORS | Fazer toda chamada de rede no extension host; o webview só conversa via `postMessage` |
| **Token GitHub (PAT)** | Digitado na tela e enviado no body/header | Pedir PAT é má experiência dentro do VS Code | Usar `vscode.authentication.getSession('github', ['repo'])`: login OAuth nativo, sem PAT |
| **Chave de API** | `.env` do servidor | — | `context.secrets` (SecretStorage, que usa o keychain do SO) |
| **Angular no webview** | SPA completa | Funciona, mas é pesado (~500 KB+), exige CSP com nonce, `asWebviewUri` para assets, hash routing, e o tema Material não segue o tema do VS Code | **Evitar para o MVP.** Usar UI nativa (comandos, QuickPick, TreeView de histórico) e abrir o resultado como documento Markdown no editor (preview nativo, edição, busca, salvar). Webview só para configuração, se necessário |
| **Tempo de resposta** | 120 s bloqueante | Sem feedback o usuário acha que travou | `window.withProgress` + streaming, com cancelamento via `CancellationToken` → `AbortController` |
| **Tamanho do VSIX** | — | — | Com o núcleo em TS e bundling via esbuild, o VSIX fica bem abaixo de 1 MB. Com sidecar Python seriam dezenas de MB por plataforma |

**Tauri (para comparação):**

- **Rede:** usar `tauri-plugin-http` (fetch executado pelo Rust, sem CORS) e passá-lo ao SDK via opção `fetch`. **Cuidado:** o plugin exige uma allowlist de URLs. Uma `baseUrl` configurável pelo usuário (Ollama remoto, Azure OpenAI, proxies corporativos) exige escopo amplo ou permissões dinâmicas.
- **Armazenamento:** `tauri-plugin-sql` (sqlx/SQLite) permite manter o mesmo schema. `tauri-plugin-stronghold` ou o keyring do SO para chaves.
- **Arquivos e outros:** `tauri-plugin-dialog`/`fs` para salvar `.md`/PDF.
- **Build e distribuição:** requer toolchain Rust para compilar (a equipe não precisa escrever Rust se ficar só em plugins). Instaladores Windows e macOS precisam de **assinatura de código** para não gerar alertas; considerar o custo do certificado.

---

## 5. Múltiplos provedores de IA (incluindo Ollama) e chave do usuário

### 5.1 Interface proposta

```ts
interface LLMProvider {
  id: string;                       // "openai" | "ollama" | "anthropic" | "openai-compatible"
  complete(req: {
    system: string;
    user: string;
    format: "markdown" | "json";
    temperature?: number;
    maxOutputTokens?: number;
    signal?: AbortSignal;
    onToken?: (chunk: string) => void;   // streaming opcional
  }): Promise<string>;
  capabilities(): { jsonMode: boolean; contextTokens: number; streaming: boolean };
  listModels?(): Promise<string[]>;      // útil para o Ollama (/api/tags)
}

type ProviderConfig = {
  provider: string; model: string; baseUrl?: string;
  apiKeyRef?: string;                    // referência ao SecretStorage/keychain, nunca a chave em texto
  contextTokens?: number;
};
```

`generate_markdown` e `generate_json` passam a ser uma única função com `format`.

### 5.2 Diferenças entre provedores que o código precisa tratar

| Aspecto | OpenAI | Ollama | Anthropic | Compatível com OpenAI (Azure, OpenRouter, LM Studio, Groq…) |
|---------|--------|--------|-----------|------------------------------------------------------------|
| Endpoint | `/v1/chat/completions` | `/api/chat` nativo (ou `/v1` compatível) | `/v1/messages` | `baseUrl` + `/chat/completions` |
| Autenticação | Bearer | Nenhuma (local) | `x-api-key` | Varia (Azure usa `api-key` + `api-version`) |
| Modo JSON | `response_format` | `format: "json"` ou JSON Schema | Não há flag equivalente; usar structured outputs/tool use ou instrução + parse tolerante | Varia por fornecedor |
| Limite de saída | `max_completion_tokens` | `options.num_predict` | `max_tokens` (**obrigatório**) | Geralmente `max_tokens` |
| **Janela de contexto** | Grande | **Padrão pequeno; o excedente é truncado silenciosamente.** Definir `options.num_ctx` na chamada nativa. No endpoint `/v1` não dá para definir por request | Grande | Varia |

### 5.3 Pontos de atenção

1. **Contexto no Ollama.** O bundle do GitHub (~120 mil caracteres) não cabe no contexto padrão do Ollama. Sem `num_ctx`, o modelo recebe o conteúdo cortado e gera documentação plausível, porém errada. Por isso é preciso:
   - usar a API nativa do Ollama (não a `/v1`);
   - tornar `MAX_TOTAL_CHARS`, `MAX_FILE_CHARS` e `MAX_FILES` dependentes de `capabilities().contextTokens`, em vez de constantes;
   - para repositórios grandes, considerar map-reduce (resumir por pasta e depois consolidar).
2. **JSON com modelos menores.** Modelos locais erram mais o formato.
   - O `_parse_json_object` tolerante do `template_ai_skeleton` deve ser reaproveitado também no avaliador. Hoje, JSON inválido gera erro 400.
   - Em caso de falha de parse, o avaliador deve ser conservador (`needs_update=true`, `confidence="low"`), coerente com a regra "em dúvida, atualize" que já está no prompt.
3. **Prompts em português.** Validar a qualidade com os modelos locais que o time pretende usar **antes** de investir no porte. É o maior risco do projeto e o mais barato de medir (ver etapa 1 na seção 6).
4. **Erros tipados.** Criar `AuthError`, `RateLimitError`, `ContextLengthError`, `ProviderUnavailableError` (Ollama desligado) e `TimeoutError`, cada um com uma mensagem útil. Hoje tudo vira `str(e)`.
5. **Streaming.** É desejável na extensão e no desktop (progresso visível). Não é obrigatório no MVP.

### 5.4 Chave de API do usuário

| Ambiente | Onde guardar | Observação |
|----------|--------------|------------|
| Extensão VS Code | `ExtensionContext.secrets` | Criptografado pelo keychain do SO; nunca em `settings.json` |
| Tauri | `tauri-plugin-stronghold` ou keyring do SO | Nunca em `localStorage` nem no SQLite em texto puro |
| Web (se mantido) | Tabela `user_provider_settings` com a chave **criptografada** (ex.: Fernet, com chave-mestra fora do banco) | Exige **migração de schema**, e hoje não há Alembic. Introduzir Alembic primeiro. A chave nunca volta ao frontend (mostrar só `sk-…abcd`) |

Regras gerais:

- Ordem de resolução: chave do usuário → chave do servidor (opcional, só no web) → erro claro.
- Nunca logar a chave. Aplicar `SecretStr` também ao `ProviderConfig` no Python.
- Botão "Testar conexão", que faz uma chamada mínima e, no Ollama, chama `listModels()`.

### 5.5 Privacidade

- Com provedores em nuvem, o código do usuário sai da máquina. O Ollama resolve isso, e esse é um argumento forte para o uso corporativo.
- Hoje `ALLOWED_SUFFIXES` inclui `.json`, `.yaml` e `.toml`, que podem conter segredos. O `.env` já é excluído. Recomenda-se:
  - adicionar filtro de arquivos sensíveis (`*secret*`, `appsettings.*.json`, `*.pem` etc.);
  - respeitar o `.gitignore` no coletor local.

---

## 6. Ordem de execução recomendada

### Etapa 0 — Preparação (2 a 3 d)

- Testes de caracterização no backend Python: prompts gerados, decisões do `documentation_evaluator`, pós-processamento do `template_ai_skeleton`, `_extract_snippet` e `parse_github_url`.
- Extrair os prompts para arquivos.
- Remover `autodoc.db` do git.

### Etapa 1 — Multiprovedor no Python atual (3 a 4 d)

- Introduzir `LLMProvider` no backend e implementar Ollama (API nativa, `num_ctx`) e OpenAI-compatível.
- Rodar os 3 templates em 2 ou 3 repositórios reais com os modelos locais candidatos.
- **Por que primeiro:** é o experimento mais barato para responder "o Ollama gera documentação boa o suficiente?". Se a resposta for não, muda o posicionamento do produto (Ollama como opção secundária) antes de gastar semanas no porte. De quebra, o web e o CI já ganham multiprovedor.

### Etapa 2 — Núcleo TypeScript `@autodoc/core` (13 a 18 d)

- Porte conforme a tabela 3.2, com os mesmos casos de teste (vitest) e sem nenhuma dependência de `vscode`, `@tauri-apps` ou Angular.

### Etapa 3 — Extensão VS Code MVP (5 a 8 d)

- **Comandos:**
  - "AutoDoc: Documentar arquivo atual";
  - "…seleção";
  - "…workspace";
  - "Avaliar se o README precisa ser atualizado";
  - "Publicar no GitHub" (ou simplesmente gravar o arquivo e deixar o usuário commitar pelo Git do VS Code, que é mais natural).
- **Configuração:** provedor, modelo e `baseUrl` em `contributes.configuration`; chave em SecretStorage.
- **Templates:** `.autodoc/templates/*.md` no workspace mais os padrões embarcados.
- **Saída:** documento Markdown aberto no editor, com preview nativo.
- **Depois do MVP** (+5 a 8 d): TreeView de histórico, webview de configurações, streaming, template a partir de exemplo e publicação no Marketplace (publisher, ícone, README, CI de empacotamento).

### Etapa 4 — App desktop Tauri (8 a 12 d)

- Criar a interface `AutoDocBackend` no Angular. A implementação `HttpBackend` mantém o web funcionando e a `LocalBackend` usa `@autodoc/core` + plugins Tauri.
- Remover login/register do build desktop e adicionar uma tela de Configurações (provedor, modelo, chave, testar conexão).
- Substituir download, impressão, clipboard e `window.open` pelas APIs dos plugins.
- Usar `tauri-plugin-sql` com o mesmo schema (sem `users`) e **migrar** um `autodoc.db` existente, se fizer sentido.
- Empacotar e assinar para Windows (MSI/NSIS) e, se necessário, macOS e Linux.

### Etapa 5 — Decidir o futuro do web (em aberto)

- Manter o Python (duplicação controlada pelos prompts e testes compartilhados) ou migrar para Node sobre `@autodoc/core`.
- O pipeline Azure pode passar a usar uma **CLI** fina sobre o núcleo (`npx autodoc evaluate …`), sem precisar de servidor nem login. Isso elimina o usuário `demo` e o JWT no CI.

### Prós e contras dos caminhos alternativos

| Caminho | Prós | Contras |
|---------|------|---------|
| **Recomendado: 0 → 1 → 2 → 3 → 4** | Mede o maior risco (qualidade do Ollama) antes de investir; o núcleo TS serve extensão, desktop e uma futura CLI; a extensão sai leve e sem binários | Mais semanas até o primeiro artefato novo (~4 a 5 semanas até a extensão); duplicação temporária Python/TS |
| **Tauri primeiro, com sidecar Python** | Entrega rápida de um desktop (~2 semanas); reaproveita 100% do backend e quase 100% do Angular | Não ajuda a extensão; sidecar PyInstaller (tamanho, antivírus, porta local); tende a virar solução definitiva e travar o porte |
| **Extensão primeiro, com sidecar Python** | Reaproveita o backend | VSIX por plataforma e pesado; exige Python ou binário na máquina do usuário; difícil publicar no Marketplace; é a pior experiência do usuário entre as opções |
| **Extensão como cliente de backend hospedado** | Mais rápido de todos (~1 semana para uma extensão fina) | Custo e operação de servidor; código e chaves passam pelo servidor; Ollama local não funciona de forma natural; exige manter a autenticação |
| **Tauri e extensão em paralelo sobre o núcleo** | Menor tempo total, se houver 2 pessoas | Mudanças de interface do núcleo afetam as duas frentes; só vale após o núcleo estabilizar (etapa 2 concluída) |

---

## 7. Outros achados (não bloqueantes, mas relevantes para o porte)

- `fetch_repo_text_bundle` declara retornar `list[tuple[str, str]]` no segundo elemento, mas retorna `str`. É uma anotação errada; atenção ao portar para TS, que tem tipagem estrita.
- `datetime.utcnow()` está depreciado no Python 3.12+ e grava datas "naive". Ao migrar dados para o Tauri, assumir que estão em UTC.
- O frontend declara `CommitGithubReadmeRequest.content` e `github_token` como obrigatórios, enquanto o backend aceita `doc_id` alternativo. Os modelos TS e Python já divergem, e o núcleo compartilhado resolve isso.
- O frontend não tem tela para `evaluate` nem `sync`. Na extensão, "Avaliar se o README precisa ser atualizado" é um comando natural e diferencial.
- O segredo JWT padrão é `"change-me-in-production"` e existe o usuário seed `demo/demo`. Isso é irrelevante no local, mas deve ser corrigido se o web for publicado.
- Não há rate limiting nem fila. Gerações longas ocupam um worker do Uvicorn durante até 120 s (as rotas síncronas rodam no threadpool).
