"""Add relation_type to node_documents table.

Supports distinguishing between 'output' (default, existing behavior)
and 'source' (workflow input) document relationships.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202601130010"
down_revision = "202601100009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "node_documents",
        sa.Column(
            "relation_type",
            sa.String(16),
            nullable=False,
            server_default="output",
        ),
    )


def downgrade() -> None:
    op.drop_column("node_documents", "relation_type")
