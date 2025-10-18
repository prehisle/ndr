from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field
from pydantic.config import ConfigDict


class DocumentCreate(BaseModel):
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUpdate(BaseModel):
    title: str | None = None
    metadata: dict[str, Any] | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    # ORM 属性名为 metadata_，仅用于内部取值，不直接输出
    metadata_: dict[str, Any] = Field(default_factory=dict, exclude=True)
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @computed_field(alias="metadata")
    def metadata(self) -> dict[str, Any]:
        return self.metadata_


class DocumentsPage(BaseModel):
    page: int
    size: int
    total: int
    items: list[DocumentOut]
