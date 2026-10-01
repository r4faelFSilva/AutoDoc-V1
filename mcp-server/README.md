# AutoDoc MCP Server

Superfície IDE do AutoDoc via Model Context Protocol: um cliente fino da API
AutoDoc que expõe templates, geração de documentação (com modo profundo
opt-in) e geração de testes para a IA da IDE.

## Ferramentas

| Tool | Descrição |
|---|---|
| `list_templates` | Lista os templates disponíveis |
| `get_template` | Conteúdo completo de um template |
| `generate_doc` | Documenta um trecho/arquivo de código |
| `generate_doc_from_github` | Documenta um repositório GitHub |
| `generate_tests` | Gera testes unitários para um arquivo de código (execução conforme `TESTGEN_EXECUTION` do backend) |
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
      "command": "<caminho-do-projeto>/backend/.venv/Scripts/python.exe",
      "args": ["<caminho-do-projeto>/mcp-server/server.py"],
      "env": {
        "AUTODOC_API_URL": "http://localhost:8000",
        "AUTODOC_EMAIL": "<seu-email-no-autodoc>",
        "AUTODOC_PASSWORD": "<sua-senha>"
      }
    }
  }
}
```

- **Claude Code**: `claude mcp add autodoc -- <command acima>` ou cole o JSON em `.mcp.json` do projeto.
- **Cursor**: Settings → MCP → Add new server (mesmo JSON).

No Linux/macOS o Python do venv fica em `<caminho-do-projeto>/backend/.venv/bin/python`.

`AUTODOC_EMAIL` e `AUTODOC_PASSWORD` são obrigatórios: o servidor não inicia sem eles.

## Modo hospedado (SSE)

```powershell
python server.py sse   # expõe em http://127.0.0.1:8765/sse
```

Por padrão o SSE só aceita conexões da própria máquina. Para expor em outra
interface, defina `AUTODOC_MCP_HOST` (ex.: `0.0.0.0`) e `AUTODOC_MCP_PORT`.
O servidor MCP não tem autenticação própria: quem alcançar a porta usa a
conta configurada em `AUTODOC_EMAIL`. Só exponha em rede confiável.

Na IDE, configure a conexão SSE apontando para `http://<host>:8765/sse`.

## Exemplo de uso na IDE

> "Usando o MCP AutoDoc, gere a documentação deste projeto no README.md
> com o template 4 e análise profunda."

A IA da IDE chama `list_templates` → `generate_doc` (com `depth="deep"`)
e escreve o resultado no arquivo.
