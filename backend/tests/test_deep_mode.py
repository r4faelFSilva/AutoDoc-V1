"""E2E do modo profundo com provider roteirizado: outline → drafts → verify
(com divergência de rota detectada deterministicamente) → rewrite → assemble
→ persist → score."""

import json
import re
import time

from app.core.llm import ChatResult

CODE = '''from fastapi import APIRouter

router = APIRouter()

@router.get("/pedidos/{pedido_id}")
def obter_pedido(pedido_id: int):
    return {"id": pedido_id}
'''


class FakeDeepProvider:
    def __init__(self):
        self.calls: list[str] = []

    async def chat(self, *, system_prompt, user_content, json_mode=False, max_output_tokens=None, temperature=0.3):
        if "planeja a estrutura" in system_prompt:
            self.calls.append("outline")
            text = json.dumps(
                {
                    "sections": [
                        {"title": "Visão Geral", "goal": "resumo do projeto", "relevant_files": ["api.py"]},
                        {"title": "Endpoints", "goal": "documentar rotas", "relevant_files": ["api.py"]},
                    ]
                }
            )
        elif "UMA seção" in system_prompt:
            self.calls.append("draft")
            title = re.search(r'"## (.+?)"', system_prompt).group(1)
            if title == "Endpoints":
                # menciona rota inexistente de propósito → verify deve flagrar
                text = f"## {title}\n\nA API expõe `GET /pedidos/{{pedido_id}}` e também `GET /rota-fantasma`."
            else:
                text = f"## {title}\n\nProjeto de exemplo com FastAPI."
        elif "audita documentação" in system_prompt:
            self.calls.append("verify")
            text = json.dumps({"issues": []})
        elif "corrige uma seção" in system_prompt:
            self.calls.append("rewrite")
            text = "## Endpoints\n\nA API expõe `GET /pedidos/{pedido_id}`."
        else:
            self.calls.append("other")
            text = "# Doc"
        return ChatResult(text=text, model="fake-deep", input_tokens=5, output_tokens=7)


def _wait_terminal(client, headers, run_id, timeout=20.0):
    deadline = time.monotonic() + timeout
    run = None
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in ("completed", "failed", "cancelled"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run não terminou: {run}")


def test_deep_mode_completo(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    provider = FakeDeepProvider()
    monkeypatch.setattr(llm, "get_provider", lambda: provider)

    resp = client.post(
        "/api/agents/documentador/runs",
        headers=auth_headers,
        json={
            "input": {
                "source": "paste",
                "template_id": 1,
                "depth": "deep",
                "code": CODE,
                "filename": "api.py",
            }
        },
    )
    assert resp.status_code == 202, resp.text
    run = _wait_terminal(client, auth_headers, resp.json()["id"])
    assert run["status"] == "completed", run

    # pipeline percorrido na ordem esperada
    assert provider.calls[0] == "outline"
    assert provider.calls.count("draft") == 2
    assert "verify" in provider.calls
    assert "rewrite" in provider.calls  # rota fantasma flagrada e corrigida

    out = run["output"]
    assert out["depth"] == "deep"
    assert out["sections_planned"] == 2
    assert out["sections_flagged"] >= 1

    # documento final: marcador AutoDoc, seções montadas e correção aplicada
    doc = client.get(f"/api/history/{out['doc_id']}", headers=auth_headers).json()
    assert "<!-- autodoc:generated -->" in doc["content"]
    assert "## Visão Geral" in doc["content"]
    assert "rota-fantasma" not in doc["content"]

    # métricas gravadas em evaluations
    from app.database import SessionLocal
    from app.models.agent_run import Evaluation

    db = SessionLocal()
    try:
        metrics = {
            e.metric: e.score
            for e in db.query(Evaluation).filter(Evaluation.run_id == run["id"]).all()
        }
    finally:
        db.close()
    assert metrics["sections_planned"] == 2.0
    assert metrics["section_coverage"] == 1.0
    assert 0.0 <= metrics["verified_ratio"] < 1.0


def test_quick_continua_sendo_padrao(client, auth_headers):
    """Sem o campo depth, o input valida como quick — garantia do opt-in."""
    from app.agents.documentador.graph import DocumentadorInput

    parsed = DocumentadorInput(source="paste", template_id=1, code="x = 1")
    assert parsed.depth == "quick"
