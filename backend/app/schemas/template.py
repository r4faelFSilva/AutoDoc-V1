from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TemplateBase(BaseModel):
    name: str
    description: str
    content: str
    type: str = Field(pattern="^(technical|functional)$")


class CreateTemplateRequest(TemplateBase):
    pass


class TemplateResponse(TemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime | None = None


class GenerateTemplateFromExampleRequest(BaseModel):
    example_markdown: str = Field(min_length=80, max_length=100_000)
    type: str = Field(default="technical", pattern="^(technical|functional)$")


class GenerateTemplateFromExampleResponse(BaseModel):
    name: str
    description: str
    content: str
    type: str
