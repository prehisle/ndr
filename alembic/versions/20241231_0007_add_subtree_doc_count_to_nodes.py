"""Add subtree_doc_count column to nodes for caching document counts."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202412310007"
down_revision = "202410220006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "subtree_doc_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("nodes", "subtree_doc_count")
