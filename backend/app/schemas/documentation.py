from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, SecretStr, field_validator


class GenerateRequest(BaseModel):
    code: str
    template_id: str
    output_type: str = Field(pattern="^(technical|functional)$")
    filename: str | None = None


class GenerateGithubRequest(BaseModel):
    github_url: str
    template_id: str
    output_type: str = Field(pattern="^(technical|functional)$")
    branch: str | None = None


class DocumentationRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    filename: str
    template_id: str
    template_name: str
    output_type: str
    status: str
    created_at: datetime
    github_url: str | None = None


class UpdateDocumentationRequest(BaseModel):
    content: str


class SearchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    template_name: str
    output_type: str
    snippet: str
    created_at: datetime


class DashboardStatsResponse(BaseModel):
    total_docs: int
    last_doc: DocumentationRecordResponse | None = None
    available_templates: int


class CommitGithubReadmeRequest(BaseModel):
    github_url: str
    content: str = Field(min_length=1, max_length=500_000)
    github_token: SecretStr
    branch: str | None = None
    target_path: str = "README.md"
    commit_message: str = Field(
        default="docs: atualiza documentação via AutoDoc",
        max_length=500,
    )

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: str) -> str:
        text = v.strip()
        if not text:
            raise ValueError("Conteúdo da documentação não pode estar vazio.")
        return text


class CommitGithubReadmeResponse(BaseModel):
    commit_sha: str
    commit_url: str
    target_path: str
    branch: str
