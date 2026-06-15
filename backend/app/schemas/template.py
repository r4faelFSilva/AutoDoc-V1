from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("example_markdown")
    @classmethod
    def strip_and_validate_markdown(cls, v: str) -> str:
        text = v.strip()
        if len(text) < 80:
            raise ValueError("O exemplo deve ter pelo menos 80 caracteres úteis.")
        return text


class GenerateTemplateFromExampleResponse(BaseModel):
    name: str
    description: str
    content: str
    type: str
    suggested_filename: str | None = None
