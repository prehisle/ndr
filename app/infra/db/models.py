from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, TimestampMixin
from app.infra.db.types import HAS_POSTGRES_LTREE, LtreeType

METADATA_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # SQLAlchemy Declarative 保留了 "metadata" 名称，这里使用 metadata_ 作为属性名，并映射到列名 "metadata"
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", METADATA_JSON_TYPE, default=dict, nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    nodes = relationship("NodeDocument", back_populates="document")


class Node(Base, TimestampMixin):
    __tablename__ = "nodes"
    _path_index_kwargs: dict[str, Any] = (
        {"postgresql_using": "gist"} if HAS_POSTGRES_LTREE else {}
    )
    __table_args__ = (
        # ltree child/ancestor queries rely on gist; fallback to btree when gist is unavailable.
        Index("ix_nodes_path_tree", "path", **_path_index_kwargs),
        Index(
            "uq_nodes_path_active",
            "path",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_nodes_parent_name_active",
            text("coalesce(parent_path, '')"),
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    path: Mapped[str] = mapped_column(LtreeType(), nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    documents = relationship("NodeDocument", back_populates="node")


class NodeDocument(Base, TimestampMixin):
    __tablename__ = "node_documents"

    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nodes.id"), primary_key=True
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id"), primary_key=True
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    node = relationship("Node", back_populates="documents")
    document = relationship("Document", back_populates="nodes")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
