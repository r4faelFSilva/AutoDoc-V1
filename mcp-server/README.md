# AutoDoc MCP Server

Superfície IDE do AutoDoc via Model Context Protocol — as mesmas ferramentas
do servidor do AutoDoc (`get_template`, `generate_doc`),
agora como cliente fino da API AutoDoc, com modo profundo opt-in.

## Ferramentas

| Tool | Descrição |
|---|---|
| `list_templates` | Lista os templates disponíveis |
| `get_template` | Conteúdo completo de um template |
| `generate_doc` | Documenta um trecho/arquivo de código |
| `generate_doc_from_github` | Documenta um repositório GitHub |
| `get_run_status` | Status/tokens/erros de um run |

`depth="deep"` ativa a análise profunda (mapa de código + verificação
factual). É opt-in por custo — o padrão é sempre `quick`.

## Requisitos

- API AutoDoc rodando (`backend/run_dev.ps1`)
- Dependências instaladas no venv do backend:
  `pip install "mcp[cli]" httpx` (já cobertas pelo requirements do backend)

## Configuração no Cursor / Claude Code / VS Code (stdio)

```json
{
  "mcpServers": {
    "autodoc": {
      "command": "<caminho-do-projeto>\\backend\\.venv\\Scripts\\python.exe",
      "args": ["<caminho-do-projeto>\\mcp-server\\server.py"],
      "env": {
        "AUTODOC_API_URL": "http://localhost:8000",
        "AUTODOC_EMAIL": "demo@autodoc.dev",
        "AUTODOC_PASSWORD": "demo"
      }
    }
  }
}
```

- **Claude Code**: `claude mcp add autodoc -- <command acima>` ou cole o JSON em `.mcp.json` do projeto.
- **Cursor**: Settings → MCP → Add new server (mesmo JSON).

## Modo hospedado (SSE)

```powershell
python server.py sse   # expõe em http://localhost:8765/sse
```

Na IDE, configure a conexão SSE apontando para `http://<host>:8765/sse`.

## Exemplo de uso na IDE

> "Usando o MCP AutoDoc, gere a documentação deste projeto no README.md
> com o template 4 e análise profunda."

A IA da IDE chama `list_templates` → `generate_doc` (com `depth="deep"`)
e escreve o resultado no arquivo.
