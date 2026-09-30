"""Testa as heurísticas determinísticas do documentation_evaluator
(os caminhos que decidem sem chamar a IA)."""

from app.services.documentation_evaluator import evaluate_documentation_update
from app.services.github_changes import (
    ChangedFile,
    CommitAnalysisContext,
    LatestCommitInfo,
    RepoDocSnapshot,
)


def _ctx(
    *,
    doc_exists: bool = True,
    is_autodoc: bool = True,
    is_substantial: bool = True,
    doc_changed: bool = False,
    changed_files: list[ChangedFile] | None = None,
) -> CommitAnalysisContext:
    return CommitAnalysisContext(
        owner="acme",
        repo="demo",
        branch="main",
        target_path="README.md",
        latest_commit=LatestCommitInfo(sha="abc1234def", message="feat: x", html_url=""),
        changed_files=changed_files or [],
        doc=RepoDocSnapshot(
            target_path="README.md",
            branch="main",
            content="conteudo" if doc_exists else None,
            doc_exists=doc_exists,
            is_autodoc_documentation=is_autodoc,
            is_substantial=is_substantial,
        ),
        doc_changed_in_latest_commit=doc_changed,
    )


def test_bootstrap_quando_doc_nao_existe():
    result = evaluate_documentation_update(_ctx(doc_exists=False))
    assert result["needs_update"] is True
    assert result["evaluation_mode"] == "bootstrap"


def test_bootstrap_quando_doc_esvaziada_no_commit():
    result = evaluate_documentation_update(_ctx(is_substantial=False, doc_changed=True))
    assert result["needs_update"] is True
    assert result["evaluation_mode"] == "bootstrap"


def test_bootstrap_quando_doc_nao_e_do_autodoc():
    result = evaluate_documentation_update(_ctx(is_autodoc=False))
    assert result["needs_update"] is True
    assert result["evaluation_mode"] == "bootstrap"


def test_skip_quando_commit_nao_toca_codigo():
    result = evaluate_documentation_update(_ctx(changed_files=[]))
    assert result["needs_update"] is False
    assert result["evaluation_mode"] == "skipped"


def test_ai_e_chamada_no_caminho_de_manutencao(monkeypatch):
    import app.services.documentation_evaluator as ev

    def fake_generate_json(**kwargs):
        return '{"needs_update": true, "reason": "API mudou", "confidence": "high"}'

    monkeypatch.setattr(ev.ai_openai, "generate_json", fake_generate_json)
    ctx = _ctx(changed_files=[ChangedFile(filename="app/main.py", status="modified", patch_summary="+rota nova")])
    result = evaluate_documentation_update(ctx)
    assert result["needs_update"] is True
    assert result["evaluation_mode"] == "maintenance"
    assert result["confidence"] == "high"
