from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
