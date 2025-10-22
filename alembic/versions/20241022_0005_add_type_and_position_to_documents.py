"""Add type and position to documents; index for fast filter/sort."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202410220005"
down_revision = "202410210004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns
    op.add_column(
        "documents",
        sa.Column("type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )

    # Indexes for filtering and ordering
    op.create_index("ix_documents_type", "documents", ["type"], unique=False)
    op.create_index("ix_documents_position", "documents", ["position"], unique=False)
    op.create_index(
        "ix_documents_type_position",
        "documents",
        ["type", "position"],
        unique=False,
    )

    # Populate position for existing rows based on created_at, id
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "WITH ranked AS ("
                "  SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) - 1 AS rn "
                "  FROM documents"
                ") "
                "UPDATE documents AS d "
                "SET position = ranked.rn "
                "FROM ranked "
                "WHERE d.id = ranked.id"
            )
        )
    else:
        # Generic fallback without window functions
        op.execute(
            sa.text(
                "UPDATE documents SET position = ("
                "  SELECT COUNT(*) FROM documents AS other "
                "  WHERE (other.created_at < documents.created_at "
                "         OR (other.created_at = documents.created_at AND other.id <= documents.id))"
                ") - 1"
            )
        )

    # Drop server default after backfill
    op.alter_column("documents", "position", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_documents_type_position", table_name="documents")
    op.drop_index("ix_documents_position", table_name="documents")
    op.drop_index("ix_documents_type", table_name="documents")
    op.drop_column("documents", "position")
    op.drop_column("documents", "type")