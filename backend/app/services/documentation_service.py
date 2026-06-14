from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.documentation_record import DocumentationRecord
from app.models.template import Template
from app.schemas.documentation import (
    DashboardStatsResponse,
    DocumentationRecordResponse,
    GenerateGithubRequest,
    GenerateRequest,
    SearchResultResponse,
)
from app.services import ai_openai, template_service
from app.services.github_archive import GitHubArchiveError, fetch_repo_text_bundle, parse_github_url


def _to_doc_response(r: DocumentationRecord) -> DocumentationRecordResponse:
    return DocumentationRecordResponse(
        id=str(r.id),
        content=r.content,
        filename=r.filename,
        template_id=str(r.template_id),
        template_name=r.template_name,
        output_type=r.output_type,
        status=r.status,
        created_at=r.created_at,
        github_url=r.github_url,
    )


def _system_prompt(*, template: Template, output_type: str) -> str:
    mode = "técnica" if output_type == "technical" else "funcional (onboarding)"
    return (
        "Você é um assistente que gera documentação de software em Markdown, em português do Brasil.\n"
        f"O usuário pediu saída no modo {mode}.\n\n"
        "Instruções do template (siga com prioridade):\n"
        f"{template.content}\n\n"
        "Regras: responda apenas com Markdown válido; use títulos, listas e blocos de código quando útil."
    )


def _parse_template_id(template_id: str) -> int:
    try:
        return int(template_id)
    except ValueError:
        return -1


def generate_from_code(
    db: Session,
    *,
    user_id: int,
    body: GenerateRequest,
    source: str = "paste",
) -> DocumentationRecordResponse:
    tid = _parse_template_id(body.template_id)
    template = template_service.get_template(db, tid)
    if not template:
        raise ValueError("Template não encontrado.")

    filename = body.filename or "codigo.txt"
    user_block = (
        f"Arquivo de referência: `{filename}`\n\n"
        "Conteúdo para analisar:\n\n"
        f"```\n{body.code}\n```\n"
    )
    system = _system_prompt(template=template, output_type=body.output_type)
    try:
        markdown = ai_openai.generate_markdown(system_prompt=system, user_content=user_block)
        status = "completed"
    except ai_openai.AIServiceError as e:
        markdown = f"# Erro na geração\n\n{str(e)}"
        status = "failed"

    rec = DocumentationRecord(
        user_id=user_id,
        content=markdown,
        filename=filename,
        template_id=template.id,
        template_name=template.name,
        output_type=body.output_type,
        status=status,
        created_at=datetime.utcnow(),
        github_url=None,
        source=source,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _to_doc_response(rec)


def generate_from_github(db: Session, *, user_id: int, body: GenerateGithubRequest) -> DocumentationRecordResponse:
    tid = _parse_template_id(body.template_id)
    template = template_service.get_template(db, tid)
    if not template:
        raise ValueError("Template não encontrado.")

    try:
        owner, repo, branch = parse_github_url(body.github_url)
        ref, bundle_text, _warnings = fetch_repo_text_bundle(owner=owner, repo=repo, branch=branch or body.branch)
    except GitHubArchiveError as e:
        raise ValueError(str(e)) from e

    if body.branch and not branch:
        ref_used = body.branch
    else:
        ref_used = ref

    filename = f"{owner}-{repo}-doc.md"
    system = _system_prompt(template=template, output_type=body.output_type)
    user_block = (
        f"O código abaixo foi obtido do repositório público `{owner}/{repo}` (ref: `{ref_used}`).\n"
        "Gere uma documentação consolidada do projeto como um todo.\n\n"
        + bundle_text
    )
    try:
        markdown = ai_openai.generate_markdown(system_prompt=system, user_content=user_block)
        status = "completed"
    except ai_openai.AIServiceError as e:
        markdown = f"# Erro na geração\n\n{str(e)}"
        status = "failed"

    rec = DocumentationRecord(
        user_id=user_id,
        content=markdown,
        filename=filename,
        template_id=template.id,
        template_name=template.name,
        output_type=body.output_type,
        status=status,
        created_at=datetime.utcnow(),
        github_url=body.github_url.strip(),
        source="github",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _to_doc_response(rec)


def list_history(db: Session, *, user_id: int) -> list[DocumentationRecordResponse]:
    rows = (
        db.query(DocumentationRecord)
        .filter(DocumentationRecord.user_id == user_id)
        .order_by(DocumentationRecord.created_at.desc())
        .all()
    )
    return [_to_doc_response(r) for r in rows]


def get_by_id(db: Session, *, user_id: int, doc_id: int) -> DocumentationRecordResponse | None:
    r = (
        db.query(DocumentationRecord)
        .filter(DocumentationRecord.id == doc_id, DocumentationRecord.user_id == user_id)
        .first()
    )
    return _to_doc_response(r) if r else None


def update_content(db: Session, *, user_id: int, doc_id: int, content: str) -> DocumentationRecordResponse | None:
    rec = (
        db.query(DocumentationRecord)
        .filter(DocumentationRecord.id == doc_id, DocumentationRecord.user_id == user_id)
        .first()
    )
    if not rec:
        return None
    rec.content = content
    db.commit()
    db.refresh(rec)
    return _to_doc_response(rec)


def delete_by_id(db: Session, *, user_id: int, doc_id: int) -> bool:
    rec = (
        db.query(DocumentationRecord)
        .filter(DocumentationRecord.id == doc_id, DocumentationRecord.user_id == user_id)
        .first()
    )
    if not rec:
        return False
    db.delete(rec)
    db.commit()
    return True


def _extract_snippet(content: str, query: str, context: int = 160) -> str:
    """Retorna um trecho do conteúdo em volta do termo encontrado, sem markdown."""
    clean = (
        content.replace('#', '')
               .replace('*', '')
               .replace('`', '')
               .replace('\n', ' ')
    )
    # colapsa espaços múltiplos
    while '  ' in clean:
        clean = clean.replace('  ', ' ')
    clean = clean.strip()

    idx = clean.lower().find(query.lower())
    if idx == -1:
        return (clean[:context] + '…') if len(clean) > context else clean

    half = context // 2
    start = max(0, idx - half)
    end = min(len(clean), idx + len(query) + half)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = '…' + snippet
    if end < len(clean):
        snippet = snippet + '…'
    return snippet


def search(
    db: Session,
    *,
    user_id: int,
    query: str,
    limit: int = 8,
) -> list[SearchResultResponse]:
    if not query.strip():
        return []
    pattern = f'%{query.strip()}%'
    records = (
        db.query(DocumentationRecord)
        .filter(
            DocumentationRecord.user_id == user_id,
            or_(
                DocumentationRecord.content.ilike(pattern),
                DocumentationRecord.filename.ilike(pattern),
                DocumentationRecord.template_name.ilike(pattern),
            ),
        )
        .order_by(DocumentationRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchResultResponse(
            id=str(r.id),
            filename=r.filename,
            template_name=r.template_name,
            output_type=r.output_type,
            snippet=_extract_snippet(r.content, query.strip()),
            created_at=r.created_at,
        )
        for r in records
    ]


def dashboard_stats(db: Session, *, user_id: int) -> DashboardStatsResponse:
    total = db.query(func.count(DocumentationRecord.id)).filter(DocumentationRecord.user_id == user_id).scalar() or 0
    last = (
        db.query(DocumentationRecord)
        .filter(DocumentationRecord.user_id == user_id)
        .order_by(DocumentationRecord.created_at.desc())
        .first()
    )
    templates_n = template_service.count_templates(db)
    return DashboardStatsResponse(
        total_docs=int(total),
        last_doc=_to_doc_response(last) if last else None,
        available_templates=int(templates_n),
    )
