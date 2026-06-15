"""Avalia se a documentação do repositório precisa ser regenerada após um commit."""

from __future__ import annotations

import json

from app.services import ai_openai
from app.services.github_changes import CommitAnalysisContext


class DocumentationEvaluatorError(Exception):
    pass


def evaluate_documentation_update(ctx: CommitAnalysisContext) -> dict[str, str | bool | int]:
    """
    Retorna needs_update, reason, confidence, latest_commit_sha, latest_commit_message,
    doc_exists, changed_files_count.
    """
    if not ctx.doc.doc_exists:
        return {
            "needs_update": True,
            "reason": f"O arquivo `{ctx.target_path}` não existe no repositório; documentação deve ser criada.",
            "confidence": "high",
            "latest_commit_sha": ctx.latest_commit.sha,
            "latest_commit_message": ctx.latest_commit.message,
            "doc_exists": False,
            "changed_files_count": len(ctx.changed_files),
        }

    if not ctx.changed_files:
        return {
            "needs_update": False,
            "reason": (
                f"O último commit ({ctx.latest_commit.sha[:7]}) não alterou arquivos de código relevantes "
                f"além de `{ctx.target_path}`."
            ),
            "confidence": "high",
            "latest_commit_sha": ctx.latest_commit.sha,
            "latest_commit_message": ctx.latest_commit.message,
            "doc_exists": True,
            "changed_files_count": 0,
        }

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
        f"Arquivo de documentação alvo: `{ctx.target_path}`\n\n"
        f"Último commit: {ctx.latest_commit.sha}\n"
        f"Mensagem: {ctx.latest_commit.message}\n\n"
        f"Arquivos alterados no commit ({len(ctx.changed_files)}):\n{files_block}\n\n"
        f"Conteúdo atual de `{ctx.target_path}`:\n\n```markdown\n{doc_preview}\n```\n"
    )

    system_prompt = (
        "Você analisa se a documentação Markdown de um projeto de software precisa ser atualizada "
        "após um commit no código.\n"
        "Responda APENAS com JSON válido no formato:\n"
        '{"needs_update": boolean, "reason": string, "confidence": "high"|"medium"|"low"}\n\n'
        "Regras:\n"
        "- needs_update=true se mudanças no código afetam APIs, arquitetura, setup, fluxos ou "
        "informações que a doc deveria descrever.\n"
        "- needs_update=false se as mudanças são cosméticas, refatoração interna sem impacto na doc, "
        "ou arquivos irrelevantes para documentação.\n"
        "- Seja conservador: em dúvida, prefira needs_update=true.\n"
        "- reason em português do Brasil, uma ou duas frases objetivas."
    )

    try:
        raw = ai_openai.generate_json(system_prompt=system_prompt, user_content=user_content)
        data = json.loads(raw)
    except ai_openai.AIServiceError as e:
        raise DocumentationEvaluatorError(str(e)) from e
    except json.JSONDecodeError as e:
        raise DocumentationEvaluatorError("Resposta da IA em formato inválido.") from e

    needs_update = bool(data.get("needs_update", True))
    reason = str(data.get("reason") or "Análise concluída pela IA.")
    confidence = str(data.get("confidence") or "medium")
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    return {
        "needs_update": needs_update,
        "reason": reason,
        "confidence": confidence,
        "latest_commit_sha": ctx.latest_commit.sha,
        "latest_commit_message": ctx.latest_commit.message,
        "doc_exists": ctx.doc.doc_exists,
        "changed_files_count": len(ctx.changed_files),
    }
