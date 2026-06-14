from datetime import datetime

from sqlalchemy.orm import Session

from app.models.template import Template
from app.models.user import User
from app.services.auth_service import hash_password


def run_seed(db: Session) -> None:
    if db.query(User).count() == 0:
        demo = User(
            email="demo@autodoc.dev",
            hashed_password=hash_password("demo"),
            created_at=datetime.utcnow(),
        )
        db.add(demo)
        db.commit()

    if db.query(Template).count() == 0:
        templates = [
            Template(
                id=1,
                name="Documentação de API REST",
                description="Gera documentação técnica completa de endpoints REST",
                content=(
                    "Analise o código abaixo e gere documentação técnica de API REST com: "
                    "endpoints, parâmetros, retornos e exemplos."
                ),
                type="technical",
                created_at=datetime(2026, 4, 10, 10, 0, 0),
            ),
            Template(
                id=2,
                name="Onboarding de Módulo",
                description="Documentação funcional para novos integrantes",
                content=(
                    "Explique o código abaixo de forma acessível para desenvolvedores juniores, "
                    "focando no propósito e fluxo do módulo."
                ),
                type="functional",
                created_at=datetime(2026, 4, 15, 14, 30, 0),
            ),
            Template(
                id=3,
                name="Revisão de Arquitetura",
                description="Análise técnica da estrutura e padrões do código",
                content=(
                    "Analise a arquitetura do código, identifique padrões de design, "
                    "dependências e potenciais melhorias."
                ),
                type="technical",
                created_at=datetime(2026, 5, 1, 9, 0, 0),
            ),
        ]
        for t in templates:
            db.merge(t)
        db.commit()
