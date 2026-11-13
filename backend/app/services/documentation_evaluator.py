"""Avalia se a documentação do repositório precisa ser regenerada após um commit."""

from __future__ import annotations

from app.services import ai_text
from app.services.github_changes import CommitAnalysisContext


class DocumentationEvaluatorError(Exception):
    pass


def _base_result(ctx: CommitAnalysisContext) -> dict[str, str | bool | int]:
    return {
        "latest_commit_sha": ctx.latest_commit.sha,
        "latest_commit_message": ctx.latest_commit.message,
        "doc_exists": ctx.doc.doc_exists,
        "changed_files_count": len(ctx.changed_files),
        "is_autodoc_documentation": ctx.doc.is_autodoc_documentation,
        "doc_changed_in_latest_commit": ctx.doc_changed_in_latest_commit,
    }


def _bootstrap_result(
    ctx: CommitAnalysisContext,
    *,
    reason: str,
) -> dict[str, str | bool | int]:
    return {
        **_base_result(ctx),
        "needs_update": True,
        "reason": reason,
        "confidence": "high",
        "evaluation_mode": "bootstrap",
    }


def _skipped_result(
    ctx: CommitAnalysisContext,
    *,
    reason: str,
) -> dict[str, str | bool | int]:
    return {
        **_base_result(ctx),
        "needs_update": False,
        "reason": reason,
        "confidence": "high",
        "evaluation_mode": "skipped",
    }


def evaluate_documentation_update(ctx: CommitAnalysisContext) -> dict[str, str | bool | int]:
    """
    Retorna needs_update, reason, confidence, evaluation_mode e metadados do commit/doc.
    """
    if not ctx.doc.doc_exists:
        return _bootstrap_result(
            ctx,
            reason=f"O arquivo `{ctx.target_path}` não existe no repositório; documentação será criada.",
        )

    if ctx.doc_changed_in_latest_commit and not ctx.doc.is_substantial:
        return _bootstrap_result(
            ctx,
            reason=(
                f"A documentação em `{ctx.target_path}` foi removida ou esvaziada no último commit; "
                "será regenerada."
            ),
        )

    if not ctx.doc.is_substantial:
        return _bootstrap_result(
            ctx,
            reason=(
                f"`{ctx.target_path}` existe, mas não contém documentação técnica suficiente; "
                "será gerada do zero."
            ),
        )

    if not ctx.doc.is_autodoc_documentation:
        return _bootstrap_result(
            ctx,
            reason=(
                f"`{ctx.target_path}` não foi gerado pelo AutoDoc (marcador ausente); "
                "documentação será criada do zero."
            ),
        )

    if not ctx.changed_files:
        return _skipped_result(
            ctx,
            reason=(
                f"Documentação AutoDoc intacta. O último commit ({ctx.latest_commit.sha[:7]}) "
                f"não alterou arquivos de código relevantes."
            ),
        )

    return _evaluate_with_ai(ctx)


def _evaluate_with_ai(ctx: CommitAnalysisContext) -> dict[str, str | bool | int]:
    files_block = "\n".join(
        f"- [{f.status}] {f.filename}"
        + (f"\n  ```diff\n{f.patch_summary}\n  ```" if f.patch_summary else "")
        for f in ctx.changed_files
    )
    doc_preview = ctx.doc.content or ""
    if len(doc_preview) > 12_000:
        doc_preview = doc_preview[:12_000] + "\n\n…(documentação truncada para análise)"

    user_content = (
        f"Repositório: {ctx.owner}/{ctx.repo} (branch: {ctx.branch})\n"
        f"Arquivo de documentação alvo: `{ctx.target_path}`\n"
        "Esta documentação JÁ FOI gerada pelo AutoDoc (marcador presente).\n\n"
        f"Último commit: {ctx.latest_commit.sha}\n"
        f"Mensagem: {ctx.latest_commit.message}\n\n"
        f"Arquivos de código alterados no commit ({len(ctx.changed_files)}):\n{files_block}\n\n"
        f"Conteúdo atual de `{ctx.target_path}`:\n\n```markdown\n{doc_preview}\n```\n"
    )

    system_prompt = (
        "Você analisa se uma documentação Markdown JÁ GERADA PELO AutoDoc precisa ser atualizada "
        "após mudanças de código em um commit.\n"
        "Responda APENAS com JSON válido no formato:\n"
        '{"needs_update": boolean, "reason": string, "confidence": "high"|"medium"|"low"}\n\n'
        "Regras:\n"
        "- Compare o diff de código com a documentação AutoDoc existente.\n"
        "- needs_update=true se mudanças no código afetam APIs, arquitetura, setup, fluxos ou "
        "informações que a doc deveria descrever.\n"
        "- needs_update=false se as mudanças são cosméticas, refatoração interna sem impacto na doc, "
        "ou arquivos irrelevantes para documentação.\n"
        "- Seja conservador: em dúvida, prefira needs_update=true.\n"
        "- reason em português do Brasil, uma ou duas frases objetivas."
    )

    try:
        raw = ai_text.generate_json(system_prompt=system_prompt, user_content=user_content)
        data = ai_text.parse_json_object(raw)
    except ai_text.AIServiceError as e:
        raise DocumentationEvaluatorError(str(e)) from e
    except ValueError as e:
        raise DocumentationEvaluatorError("Resposta da IA em formato inválido.") from e

    needs_update = bool(data.get("needs_update", True))
    reason = str(data.get("reason") or "Análise concluída pela IA.")
    confidence = str(data.get("confidence") or "medium")
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    return {
        **_base_result(ctx),
        "needs_update": needs_update,
        "reason": reason,
        "confidence": confidence,
        "evaluation_mode": "maintenance",
    }
