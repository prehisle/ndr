from typing import Any
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Text, JSON, ForeignKey, String
from sqlalchemy.orm import relationship

from app.infra.db.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # SQLAlchemy Declarative 保留了 "metadata" 名称，这里使用 metadata_ 作为属性名，并映射到列名 "metadata"
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    nodes = relationship("NodeDocument", back_populates="document")


class Node(Base, TimestampMixin):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)  # ltree 兼容占位，使用点分层级
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    documents = relationship("NodeDocument", back_populates="node")


class NodeDocument(Base):
    __tablename__ = "node_documents"

    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nodes.id"), primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("documents.id"), primary_key=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    node = relationship("Node", back_populates="documents")
    document = relationship("Document", back_populates="nodes")