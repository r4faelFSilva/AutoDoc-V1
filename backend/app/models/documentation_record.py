from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentationRecord(Base):
    __tablename__ = "documentation_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text())
    filename: Mapped[str] = mapped_column(String(512))
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    template_name: Mapped[str] = mapped_column(String(255))
    output_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    github_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="paste")

    template: Mapped["Template"] = relationship("Template", back_populates="documentation_records")
    user: Mapped["User"] = relationship("User", back_populates="documentation_records")
