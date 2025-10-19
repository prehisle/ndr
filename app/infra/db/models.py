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
CONTENT_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Document(Base, TimestampMixin):
    """Business document stored in JSON-friendly form.

    Fields
    -------
    id : database primary key（bigint，自增）。
    title : 文档标题，使用 `Text` 以兼容大文本。
    metadata_ : JSON 元数据，映射到列名 `metadata`，用于存储扩展属性。
    created_by / updated_by : 记录最近一次写入该文档的用户标识。
    created_at / updated_at / deleted_at : 来自 `TimestampMixin`，管理审计与软删。
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # SQLAlchemy Declarative 保留了 "metadata" 名称，这里使用 metadata_ 作为属性名，并映射到列名 "metadata"
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", METADATA_JSON_TYPE, default=dict, nullable=False
    )
    content: Mapped[dict[str, Any]] = mapped_column(
        CONTENT_JSON_TYPE, default=dict, nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    nodes = relationship("NodeDocument", back_populates="document")
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )


class Node(Base, TimestampMixin):
    """Tree node built on top of PostgreSQL ltree paths.

    Fields
    -------
    id : 自增主键，唯一标识节点。
    name : 节点的业务名称，用于展示。
    slug : 路径片段（与父节点组合形成 `path`）。
    parent_path : 父节点完整路径，根节点为 `None`。
    path : 当前节点的完整 ltree 路径，用于祖先/子孙查询。
    created_by / updated_by : 最近一次写入节点的用户。
    created_at / updated_at / deleted_at : `TimestampMixin` 提供的审计时间戳。
    """

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
    """Association table between nodes and documents.

    Fields
    -------
    node_id / document_id : 复合主键，指向关联的节点与文档。
    created_by / updated_by : 记录关系的创建及最近修改来源。
    created_at / updated_at / deleted_at : 继承自 `TimestampMixin` 的审计信息。
    """

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


class DocumentVersion(Base):
    """Historical snapshot of document data used for auditing and restore."""

    __tablename__ = "document_versions"
    __table_args__ = (
        Index(
            "uq_document_versions_document_version",
            "document_id",
            "version_number",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    source_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_title: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_metadata: Mapped[dict[str, Any]] = mapped_column(
        METADATA_JSON_TYPE, nullable=False, default=dict
    )
    snapshot_content: Mapped[dict[str, Any]] = mapped_column(
        CONTENT_JSON_TYPE, nullable=False, default=dict
    )
    change_summary: Mapped[dict[str, Any] | None] = mapped_column(
        CONTENT_JSON_TYPE, nullable=True
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document = relationship("Document", back_populates="versions")


class IdempotencyRecord(Base):
    """Persisted response for handling idempotent requests.

    Fields
    -------
    key : Idempotency-Key 原值，用作主键。
    request_hash : 请求方法 + 路径 + 载荷的哈希值，用于冲突检测。
    status_code : 初次执行时返回的 HTTP 状态码。
    response_body : 原始响应体（JSON 化后保存）。
    created_at : 记录创建时间。
    expires_at : 记录过期时间，可用于清理。
    """

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
