"""Кого позвали в реплике обсуждения

Revision ID: c1a7d5b93e10
Revises: d4ef51da634e
Create Date: 2026-09-08 12:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1a7d5b93e10"
down_revision: str | Sequence[str] | None = "d4ef51da634e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Пустым списком, а не NULL: «никого не звали» и «поле не заполняли» — одно
    # и то же событие, и две его записи означали бы две ветки в каждой проверке.
    op.add_column(
        "discussion_messages",
        sa.Column(
            "mentions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("discussion_messages", "mentions")
