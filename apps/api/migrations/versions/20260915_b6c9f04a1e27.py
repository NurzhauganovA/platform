"""Правка прав встроенных ролей — накладкой.

«Тендерщик без аналитики» и «закупщик, которому не нужны файлы» — это
настройка, а не новая роль: заводить рядом копию из десяти галочек ради снятия
одной значит держать два списка и однажды поправить только один.

Накладкой, а не подменой. Заводские права заданы кодом — это ответ на вопрос
«как должно быть», и терять его нельзя: «вернуть как было» пришлось бы
восстанавливать по памяти того, кто правил. Запись есть — права из неё, записи
нет — из кода.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b6c9f04a1e27"
down_revision = "a9d5c2e71f38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "role", name="role_override_role"),
    )
    op.create_index("ix_role_overrides_organization_id", "role_overrides", ["organization_id"])
    op.create_index("ix_role_overrides_role", "role_overrides", ["role"])


def downgrade() -> None:
    op.drop_index("ix_role_overrides_role", table_name="role_overrides")
    op.drop_index("ix_role_overrides_organization_id", table_name="role_overrides")
    op.drop_table("role_overrides")
