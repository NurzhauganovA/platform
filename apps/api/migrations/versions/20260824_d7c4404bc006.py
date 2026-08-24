"""Закупка может вестись лотом

Первая редакция лота: одна запись на папку закупки. Следующая миграция
заменяет её набором позиций — папки для лота мало, заказчик раскладывает один
лот по двум.

Восстановлена после удаления. Удалять выпущенную миграцию нельзя: базы, где
она уже применилась, помнят её отметку, и alembic отказывается работать —
«не могу найти ревизию». На проверочном сервере это выглядело как «migrate
didn't complete successfully: exit 255», причём в базе к тому моменту всё было
в порядке.

Revision ID: d7c4404bc006
Revises: 8d59d2f7828e
Create Date: 2026-08-24 10:31:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7c4404bc006"
down_revision: str | Sequence[str] | None = "8d59d2f7828e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tender_lots",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("folder_path", sa.String(length=1024), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_tender_lots_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_tender_lots_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_lots")),
        sa.UniqueConstraint("organization_id", "folder_path", name="organization_folder"),
    )
    op.create_index(
        op.f("ix_tender_lots_organization_id"), "tender_lots", ["organization_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_tender_lots_organization_id"), table_name="tender_lots")
    op.drop_table("tender_lots")
