"""Папки для файлов лота

Revision ID: f7b3c8d21a45
Revises: e5c9d1a4f207
Create Date: 2026-09-10 11:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b3c8d21a45"
down_revision: str | Sequence[str] | None = "e5c9d1a4f207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "lot_folders",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        # Значения по умолчанию на стороне базы: `Timestamps` в моделях
        # объявляет их через `server_default`, и таблица без них расходится с
        # моделью — `alembic check` показывает это отличием при каждом прогоне.
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["lot_cards.id"],
            name=op.f("fk_lot_folders_card_id_lot_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_lot_folders_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lot_folders")),
        sa.UniqueConstraint("card_id", "name", name="lot_folder_name"),
    )
    op.create_index(op.f("ix_lot_folders_card_id"), "lot_folders", ["card_id"])

    # Уже приложенные файлы остаются в корне: раскладывать чужую работу за
    # человека нельзя — он клал их, зная, где искать.
    op.add_column("lot_files", sa.Column("folder_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_lot_files_folder_id"), "lot_files", ["folder_id"])
    # `SET NULL`: удалённая папка возвращает файлы в корень, а не уносит их с
    # собой. Правило в базе, а не в службе: прогон или запрос мимо HTTP иначе
    # оставит висячие ссылки, и файл пропадёт из карточки молча.
    op.create_foreign_key(
        op.f("fk_lot_files_folder_id_lot_folders"),
        "lot_files",
        "lot_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_lot_files_folder_id_lot_folders"), "lot_files", type_="foreignkey")
    op.drop_index(op.f("ix_lot_files_folder_id"), table_name="lot_files")
    op.drop_column("lot_files", "folder_id")
    op.drop_index(op.f("ix_lot_folders_card_id"), table_name="lot_folders")
    op.drop_table("lot_folders")
