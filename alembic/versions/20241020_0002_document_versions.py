"""Add document content column and version history table."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202410200002"
down_revision = "202410170001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = sa.JSON()
    metadata_server_default = sa.text("'{}'")
    content_server_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        json_type = json_type.with_variant(JSONB(), "postgresql")
        metadata_server_default = sa.text("'{}'::jsonb")
        content_server_default = sa.text("'{}'::jsonb")

    op.add_column(
        "documents",
        sa.Column("content", json_type, nullable=False, server_default=content_server_default),
    )
    op.alter_column("documents", "content", server_default=None)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.BigInteger(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("source_version_number", sa.Integer(), nullable=True),
        sa.Column("snapshot_title", sa.Text(), nullable=False),
        sa.Column("snapshot_metadata", json_type, nullable=False, server_default=metadata_server_default),
        sa.Column("snapshot_content", json_type, nullable=False, server_default=content_server_default),
        sa.Column("change_summary", json_type, nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_document_versions_document_version",
        "document_versions",
        ["document_id", "version_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_document_versions_document_version", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_column("documents", "content")
