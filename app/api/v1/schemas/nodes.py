import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from pydantic.config import ConfigDict


class NodeCreate(BaseModel):
    name: str
    slug: str
    parent_path: str | None = None
    type: str | None = None

    # 仅允许符合 ltree label 的安全字符，避免出现 '.' 等分隔符导致解析错误
    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not (1 <= len(v) <= 255):
            raise ValueError("slug 长度必须在 1..255 之间")
        if not re.fullmatch(r"[a-z0-9_-]+", v):
            raise ValueError("slug 仅允许小写字母、数字、下划线与短横线 [a-z0-9_-]")
        return v


class NodeUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    parent_path: str | None = None
    type: str | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug_opt(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not (1 <= len(v) <= 255):
            raise ValueError("slug 长度必须在 1..255 之间")
        if not re.fullmatch(r"[a-z0-9_-]+", v):
            raise ValueError("slug 仅允许小写字母、数字、下划线与短横线 [a-z0-9_-]")
        return v


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    type: str | None = None
    path: str
    parent_id: int | None = None
    position: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class NodesPage(BaseModel):
    page: int
    size: int
    total: int
    items: list[NodeOut]


class NodeReorderPayload(BaseModel):
    parent_id: int | None = None
    ordered_ids: list[int] = Field(default_factory=list)
