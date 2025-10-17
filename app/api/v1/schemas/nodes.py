from typing import Any
from datetime import datetime
from pydantic import BaseModel
from pydantic.config import ConfigDict


class NodeCreate(BaseModel):
    name: str
    slug: str
    parent_path: str | None = None


class NodeUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    path: str
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