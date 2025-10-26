"""Add index on node_documents(document_id) to speed document-centric queries."""

from __future__ import annotations

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202410260007"
down_revision = "202410220006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_node_documents_document_id",
        "node_documents",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_node_documents_document_id", table_name="node_documents")

