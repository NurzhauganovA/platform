"""Свои роли с правами.

Встроенных десять, и они описывают отделы так, как они сложились у нас.
Компания молодая: появляется «снабженец без цен», «стажёр тендерного отдела»,
«бухгалтер, которому нужны только итоги». Прибивать каждую такую роль в код
значит выкладывать платформу ради одного человека.

Права хранятся списком, а сам список прав определён кодом: так нельзя выдать
право, которого никто не проверяет.

Встроенные роли в таблицу не переносятся. Их права заданы кодом и не правятся —
иначе вопрос «что сломается, если поменять» пришлось бы выяснять на работающей
платформе.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e4f81c6d92b7"
down_revision = "d3a7b95c1f64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
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
        sa.UniqueConstraint("organization_id", "key", name="custom_role_key"),
    )
    op.create_index("ix_custom_roles_organization_id", "custom_roles", ["organization_id"])
    op.create_index("ix_custom_roles_key", "custom_roles", ["key"])

    op.add_column(
        "memberships",
        sa.Column("custom_role_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # `SET NULL`: удалённая роль не уносит человека из платформы — он остаётся
    # с правами наблюдателя, и администратор видит это на экране людей.
    op.create_foreign_key(
        "memberships_custom_role_id_fkey",
        "memberships",
        "custom_roles",
        ["custom_role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_memberships_custom_role_id", "memberships", ["custom_role_id"])


def downgrade() -> None:
    op.drop_index("ix_memberships_custom_role_id", table_name="memberships")
    op.drop_constraint("memberships_custom_role_id_fkey", "memberships", type_="foreignkey")
    op.drop_column("memberships", "custom_role_id")
    op.drop_index("ix_custom_roles_key", table_name="custom_roles")
    op.drop_index("ix_custom_roles_organization_id", table_name="custom_roles")
    op.drop_table("custom_roles")
