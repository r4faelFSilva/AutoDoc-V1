from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser
from app.schemas.documentation import (
    CommitGithubReadmeRequest,
    CommitGithubReadmeResponse,
    DashboardStatsResponse,
    DocumentationRecordResponse,
    GenerateGithubRequest,
    GenerateRequest,
    SearchResultResponse,
    UpdateDocumentationRequest,
)
from app.services import documentation_service
from app.services.github_commit import GitHubCommitError, commit_markdown_file

router = APIRouter(tags=["documentation"])


@router.post("/generate", response_model=DocumentationRecordResponse)
def generate(
    body: GenerateRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> DocumentationRecordResponse:
    try:
        return documentation_service.generate_from_code(
            db,
            user_id=user.id,
            body=body,
            source="upload" if body.filename and body.filename != "código-colado.txt" else "paste",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/generate/github", response_model=DocumentationRecordResponse)
def generate_github(
    body: GenerateGithubRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> DocumentationRecordResponse:
    try:
        return documentation_service.generate_from_github(db, user_id=user.id, body=body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/generate/github/commit", response_model=CommitGithubReadmeResponse)
def commit_github_readme(
    body: CommitGithubReadmeRequest,
    _user: CurrentUser,
) -> CommitGithubReadmeResponse:
    try:
        result = commit_markdown_file(
            github_url=body.github_url,
            content=body.content,
            github_token=body.github_token.get_secret_value(),
            branch=body.branch,
            target_path=body.target_path,
            commit_message=body.commit_message,
        )
        return CommitGithubReadmeResponse(**result)
    except GitHubCommitError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/history", response_model=list[DocumentationRecordResponse])
def history(user: CurrentUser, db: Session = Depends(get_db)) -> list[DocumentationRecordResponse]:
    return documentation_service.list_history(db, user_id=user.id)


@router.get("/history/{doc_id}", response_model=DocumentationRecordResponse)
def history_by_id(
    doc_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> DocumentationRecordResponse:
    try:
        did = int(doc_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Não encontrado.")
    row = documentation_service.get_by_id(db, user_id=user.id, doc_id=did)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Não encontrado.")
    return row


@router.patch("/history/{doc_id}", response_model=DocumentationRecordResponse)
def update_history(
    doc_id: str,
    body: UpdateDocumentationRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> DocumentationRecordResponse:
    try:
        did = int(doc_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Não encontrado.")
    result = documentation_service.update_content(db, user_id=user.id, doc_id=did, content=body.content)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Não encontrado.")
    return result


@router.delete("/history/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_history(
    doc_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    try:
        did = int(doc_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Não encontrado.")
    deleted = documentation_service.delete_by_id(db, user_id=user.id, doc_id=did)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Não encontrado.")


@router.get("/search", response_model=list[SearchResultResponse])
def search_docs(
    q: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = 8,
) -> list[SearchResultResponse]:
    if not q or len(q.strip()) < 2:
        return []
    return documentation_service.search(db, user_id=user.id, query=q, limit=limit)


@router.get("/stats", response_model=DashboardStatsResponse)
def stats(user: CurrentUser, db: Session = Depends(get_db)) -> DashboardStatsResponse:
    return documentation_service.dashboard_stats(db, user_id=user.id)
