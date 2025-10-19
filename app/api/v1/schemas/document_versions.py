from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field
from pydantic.config import ConfigDict


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_number: int
    operation: str
    source_version_number: int | None = None
    created_by: str
    created_at: datetime
    change_summary: dict[str, Any] | None = None
    snapshot_title: str = Field(..., exclude=True)
    snapshot_metadata: dict[str, Any] = Field(default_factory=dict, exclude=True)
    snapshot_content: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @computed_field(alias="title")
    def title(self) -> str:
        return self.snapshot_title

    @computed_field(alias="metadata")
    def metadata(self) -> dict[str, Any]:
        return self.snapshot_metadata

    @computed_field(alias="content")
    def content(self) -> dict[str, Any]:
        return self.snapshot_content


class DocumentVersionsPage(BaseModel):
    page: int
    size: int
    total: int
    items: list[DocumentVersionOut]


class DocumentVersionDiff(BaseModel):
    title: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    content: dict[str, Any] | None = None
