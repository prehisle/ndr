"""Initial relational schema with ltree support."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.infra.db.types import LtreeType

# revision identifiers, used by Alembic.
revision = "202410170001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ltree_available = False
    if bind.dialect.name == "postgresql":
        try:
            from sqlalchemy.dialects.postgresql import ltree as _pg_ltree  # type: ignore[attr-defined]
        except ImportError:  # pragma: no cover - fallback when ltree dialect is unavailable
            _pg_ltree = None
        else:
            ltree_available = hasattr(_pg_ltree, "LTREE")
        op.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_metadata_gin", "documents", ["metadata"], postgresql_using="gin")

    op.create_table(
        "nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("parent_path", sa.String(length=2048), nullable=True),
        sa.Column("path", LtreeType(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    index_kwargs: dict[str, object] = {"postgresql_using": "gist"} if ltree_available else {}
    op.create_index("ix_nodes_path_tree", "nodes", ["path"], **index_kwargs)
    op.create_index(
        "uq_nodes_path_active",
        "nodes",
        ["path"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_nodes_parent_name_active",
        "nodes",
        [sa.text("coalesce(parent_path, '')"), "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "node_documents",
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("node_id", "document_id"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    )


def downgrade() -> None:
    op.drop_table("node_documents")
    op.drop_table("idempotency_records")
    op.drop_index("uq_nodes_parent_name_active", table_name="nodes")
    op.drop_index("uq_nodes_path_active", table_name="nodes")
    op.drop_index("ix_nodes_path_tree", table_name="nodes")
    op.drop_table("nodes")
    op.drop_index("ix_documents_metadata_gin", table_name="documents")
    op.drop_table("documents")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS ltree")
