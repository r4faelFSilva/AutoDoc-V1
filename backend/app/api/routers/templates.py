from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser
from app.schemas.template import (
    CreateTemplateRequest,
    GenerateTemplateFromExampleRequest,
    GenerateTemplateFromExampleResponse,
    TemplateResponse,
)
from app.services import template_service
from app.services.template_ai_skeleton import TemplateSkeletonError, suggest_from_example

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("/generate-from-example", response_model=GenerateTemplateFromExampleResponse)
def generate_template_from_example(
    body: GenerateTemplateFromExampleRequest,
    _user: CurrentUser,
) -> GenerateTemplateFromExampleResponse:
    try:
        data = suggest_from_example(example_markdown=body.example_markdown, doc_type=body.type)
        return GenerateTemplateFromExampleResponse(**data)
    except TemplateSkeletonError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e


@router.get("", response_model=list[TemplateResponse])
def list_templates(_user: CurrentUser, db: Session = Depends(get_db)) -> list[TemplateResponse]:
    return template_service.list_templates(db)


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    body: CreateTemplateRequest,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> TemplateResponse:
    return template_service.create_template(db, body)


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: str,
    body: CreateTemplateRequest,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> TemplateResponse:
    try:
        tid = int(template_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")
    updated = template_service.update_template(db, tid, body)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")
    return updated


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    try:
        tid = int(template_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")
    ok = template_service.delete_template(db, tid)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")
