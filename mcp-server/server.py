"""Servidor MCP do AutoDoc — superfície IDE dos agentes.

Cliente fino da API AutoDoc: nenhuma lógica de agente vive aqui. As mesmas
ferramentas principais (get_template / generate_doc) mais o fluxo novo de
runs com modo profundo opt-in.

Transportes:
    python server.py            → stdio (Cursor, Claude Code, VS Code local)
    python server.py sse        → SSE em http://127.0.0.1:8765 (hospedado)

Variáveis de ambiente:
    AUTODOC_API_URL   (padrão: http://localhost:8000)
    AUTODOC_EMAIL     obrigatória — conta do AutoDoc usada pelo MCP
    AUTODOC_PASSWORD  obrigatória
    AUTODOC_TIMEOUT   segundos de espera por geração (padrão: 300)
    AUTODOC_MCP_HOST  interface do modo SSE (padrão: 127.0.0.1)
    AUTODOC_MCP_PORT  porta do modo SSE (padrão: 8765)
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx
from mcp.server import MCPServer

API_URL = os.environ.get("AUTODOC_API_URL", "http://localhost:8000").rstrip("/")
EMAIL = os.environ.get("AUTODOC_EMAIL", "").strip()
PASSWORD = os.environ.get("AUTODOC_PASSWORD", "")
TIMEOUT_SECONDS = float(os.environ.get("AUTODOC_TIMEOUT", "300"))

mcp = MCPServer(
    "autodoc",
    instructions=(
        "Ferramentas do AutoDoc para geração de documentação técnica. "
        "Use get_template/list_templates para conhecer os formatos disponíveis e "
        "generate_doc/generate_doc_from_github para gerar documentação. "
        "depth='deep' faz análise profunda (mapa de código + verificação factual), "
        "mais lenta e cara — use apenas quando o usuário pedir."
    ),
)

_token: str | None = None


def _login(client: httpx.Client) -> str:
    global _token
    r = client.post(f"{API_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    _token = r.json()["access_token"]
    return _token


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """Chamada autenticada à API, com relogin automático em 401."""
    with httpx.Client(timeout=60.0) as client:
        token = _token or _login(client)
        r = client.request(method, f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if r.status_code == 401:
            token = _login(client)
            r = client.request(
                method, f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        return r


def _agent_run(agent: str, input_payload: dict) -> dict | str:
    """Cria um run, espera terminar e retorna o run completo (ou string de erro)."""
    r = _request("POST", f"/api/agents/{agent}/runs", json={"input": input_payload})
    if r.status_code not in (200, 202):
        return f"Erro ao criar run: HTTP {r.status_code} — {r.text[:500]}"
    run_id = r.json()["id"]

    deadline = time.monotonic() + TIMEOUT_SECONDS
    run: dict = {}
    while time.monotonic() < deadline:
        run = _request("GET", f"/api/runs/{run_id}").json()
        if run["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(2.0)

    if run.get("status") != "completed":
        return (
            f"Run {run_id} terminou com status '{run.get('status', 'timeout')}'. "
            f"Erro: {run.get('error') or 'timeout'}"
        )
    return run


def _run_and_wait(input_payload: dict) -> str:
    run = _agent_run("documentador", input_payload)
    if isinstance(run, str):
        return run
    run_id = run["id"]
    doc_id = run["output"]["doc_id"]
    doc = _request("GET", f"/api/history/{doc_id}").json()
    meta = (
        f"<!-- run_id={run_id} depth={run['output'].get('depth', 'quick')} "
        f"tokens={run['input_tokens']}+{run['output_tokens']} -->\n\n"
    )
    return meta + doc["content"]


@mcp.tool()
def list_templates() -> str:
    """Lista os templates de documentação disponíveis no AutoDoc (id, nome, descrição e tipo)."""
    r = _request("GET", "/api/templates")
    if r.status_code != 200:
        return f"Erro: HTTP {r.status_code} — {r.text[:300]}"
    rows = [
        {"id": t["id"], "name": t["name"], "description": t["description"], "type": t["type"]}
        for t in r.json()
    ]
    return json.dumps(rows, ensure_ascii=False, indent=2)


@mcp.tool()
def get_template(template_id: int) -> str:
    """Retorna o conteúdo completo (instruções) de um template de documentação do AutoDoc."""
    r = _request("GET", f"/api/templates/{template_id}")
    if r.status_code != 200:
        return f"Erro: HTTP {r.status_code} — {r.text[:300]}"
    t = r.json()
    return f"# {t['name']}\n\n{t['description']}\n\n---\n\n{t['content']}"


@mcp.tool()
def generate_doc(
    code: str,
    template_id: int = 1,
    output_type: str = "technical",
    depth: str = "quick",
    filename: str = "codigo.txt",
) -> str:
    """Gera documentação em Markdown para um trecho/arquivo de código via AutoDoc.

    Args:
        code: código-fonte a documentar.
        template_id: template do AutoDoc (use list_templates para ver as opções).
        output_type: "technical" (para devs) ou "functional" (onboarding).
        depth: "quick" (padrão, rápido) ou "deep" (análise profunda com verificação
            factual — mais lenta e cara; use apenas se o usuário pedir).
        filename: nome do arquivo de referência.
    """
    return _run_and_wait(
        {
            "source": "paste",
            "code": code,
            "template_id": template_id,
            "output_type": output_type,
            "depth": depth,
            "filename": filename,
        }
    )


@mcp.tool()
def generate_doc_from_github(
    github_url: str,
    template_id: int = 1,
    output_type: str = "technical",
    depth: str = "quick",
    branch: str = "",
) -> str:
    """Gera documentação consolidada de um repositório GitHub público via AutoDoc.

    Args:
        github_url: URL do repositório (https://github.com/dono/repo).
        template_id: template do AutoDoc (use list_templates).
        output_type: "technical" ou "functional".
        depth: "quick" (padrão) ou "deep" (análise profunda; mais lenta e cara).
        branch: branch a usar; vazio usa o padrão do repositório.
    """
    payload: dict = {
        "source": "github",
        "github_url": github_url,
        "template_id": template_id,
        "output_type": output_type,
        "depth": depth,
    }
    if branch.strip():
        payload["branch"] = branch.strip()
    return _run_and_wait(payload)


@mcp.tool()
def generate_tests(code: str, filename: str = "codigo.py") -> str:
    """Gera testes unitários para um arquivo de código via AutoDoc e tenta executá-los.

    Python: testes `unittest` (stdlib), executados em ambiente isolado quando disponível,
    com reparo automático de falhas. TS/JS: spec Jasmine (geração-apenas).

    Args:
        code: código-fonte do arquivo a testar.
        filename: nome do arquivo (a extensão define a linguagem: .py, .ts, .js).
    """
    run = _agent_run(
        "gerador_testes",
        {"source": "paste", "code": code, "filename": filename},
    )
    if isinstance(run, str):
        return run
    out = run["output"]
    header = (
        f"<!-- run_id={run['id']} status={out['status']} modo_execucao={out['execution_mode']} "
        f"reparos={out['attempts']} -->\n"
        f"Resumo: {out['summary']}\n\n"
        f"Arquivo sugerido: `{out['test_filename']}`\n\n"
    )
    return header + f"```\n{out['test_code']}\n```"


@mcp.tool()
def get_run_status(run_id: int) -> str:
    """Consulta o status, tokens e eventuais erros de um run de agente do AutoDoc."""
    r = _request("GET", f"/api/runs/{run_id}")
    if r.status_code != 200:
        return f"Erro: HTTP {r.status_code} — {r.text[:300]}"
    run = r.json()
    return json.dumps(
        {
            "id": run["id"],
            "agent": run["agent"],
            "status": run["status"],
            "error": run["error"],
            "model": run["model"],
            "tokens": f"{run['input_tokens']}+{run['output_tokens']}",
            "output": run["output"],
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    if not EMAIL or not PASSWORD:
        sys.exit("Configure AUTODOC_EMAIL e AUTODOC_PASSWORD com uma conta do AutoDoc.")
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "sse":
        mcp.run(
            transport="sse",
            host=os.environ.get("AUTODOC_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("AUTODOC_MCP_PORT", "8765")),
        )
    else:
        mcp.run()
