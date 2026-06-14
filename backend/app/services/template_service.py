from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.template import Template
from app.schemas.template import CreateTemplateRequest, TemplateResponse


def _to_response(t: Template) -> TemplateResponse:
    return TemplateResponse(
        id=str(t.id),
        name=t.name,
        description=t.description,
        content=t.content,
        type=t.type,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def list_templates(db: Session) -> list[TemplateResponse]:
    rows = db.query(Template).order_by(Template.id).all()
    return [_to_response(t) for t in rows]


def get_template(db: Session, template_id: int) -> Template | None:
    return db.query(Template).filter(Template.id == template_id).first()


def create_template(db: Session, data: CreateTemplateRequest) -> TemplateResponse:
    now = datetime.utcnow()
    t = Template(
        name=data.name,
        description=data.description,
        content=data.content,
        type=data.type,
        created_at=now,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_response(t)


def update_template(db: Session, template_id: int, data: CreateTemplateRequest) -> TemplateResponse | None:
    t = get_template(db, template_id)
    if not t:
        return None
    t.name = data.name
    t.description = data.description
    t.content = data.content
    t.type = data.type
    t.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(t)
    return _to_response(t)


def delete_template(db: Session, template_id: int) -> bool:
    t = get_template(db, template_id)
    if not t:
        return False
    db.delete(t)
    db.commit()
    return True


def count_templates(db: Session) -> int:
    return db.query(func.count(Template.id)).scalar() or 0
