from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


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
    content: str | None = Field(default=None, max_length=500_000)
    doc_id: str | None = None
    github_token: SecretStr
    branch: str | None = None
    target_path: str = "README.md"
    commit_message: str = Field(
        default="docs: atualiza documentação via AutoDoc",
        max_length=500,
    )

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: str | None) -> str | None:
        if v is None:
            return None
        text = v.strip()
        if not text:
            raise ValueError("Conteúdo da documentação não pode estar vazio.")
        return text

    @model_validator(mode="after")
    def require_content_or_doc_id(self) -> "CommitGithubReadmeRequest":
        has_content = self.content is not None and self.content.strip() != ""
        has_doc = self.doc_id is not None and self.doc_id.strip() != ""
        if has_content and has_doc:
            raise ValueError("Informe apenas content ou doc_id, não ambos.")
        if not has_content and not has_doc:
            raise ValueError("Informe content ou doc_id.")
        return self


class CommitGithubReadmeResponse(BaseModel):
    commit_sha: str
    commit_url: str
    target_path: str
    branch: str


class GithubDocEvaluateRequest(BaseModel):
    github_url: str
    github_token: SecretStr
    branch: str | None = None
    target_path: str = "README.md"


class GithubDocEvaluateResponse(BaseModel):
    needs_update: bool
    reason: str
    confidence: str
    latest_commit_sha: str
    latest_commit_message: str
    doc_exists: bool
    changed_files_count: int


class GithubDocSyncRequest(BaseModel):
    github_url: str
    github_token: SecretStr
    template_id: str
    output_type: str = Field(default="technical", pattern="^(technical|functional)$")
    branch: str | None = None
    target_path: str = "README.md"
    commit_message: str = Field(
        default="docs: atualiza documentação via AutoDoc",
        max_length=500,
    )


class GithubDocSyncResponse(BaseModel):
    action: str
    reason: str
    needs_update: bool
    doc: DocumentationRecordResponse | None = None
    commit: CommitGithubReadmeResponse | None = None
