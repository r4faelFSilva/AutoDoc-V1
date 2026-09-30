from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Project(Base):
    """Projeto acompanhado pelo AutoDoc: repo, branch e config padrão.

    Substitui o modelo ad-hoc em que cada request carrega github_url/branch;
    agentes e pipeline referenciam o projeto.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    github_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id"), nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
