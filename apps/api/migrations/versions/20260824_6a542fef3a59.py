"""Лот как набор позиций

Папки для лота мало. Разбор связывает позиции папкой и ошибается в обе
стороны: заказчик раскладывает один лот по двум папкам, а иногда наоборот —
позиции одного заключения разыгрываются порознь. Состав лота собирает человек,
и хранить его надо перечнем позиций, а не признаком у папки.

Позиция хранится папкой и названием, а не идентификатором строки: тот
считается от них же и меняется с каждым новым разбором — лот распался бы на
пустые ссылки после первого прогона ядра.

Revision ID: 6a542fef3a59
Revises: d7c4404bc006
Create Date: 2026-08-24 11:56:10.540254

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a542fef3a59"
down_revision: str | Sequence[str] | None = "d7c4404bc006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Прежние лоты не переносятся: в них лежала одна папка без перечня
    # позиций, а из папки состав не восстановить — он и был догадкой, ради
    # исправления которой всё затевалось. Записей на момент правки нигде не
    # было, а объединить заново — одно нажатие.
    op.execute(sa.text("delete from tender_lots"))
    op.drop_constraint("organization_folder", "tender_lots", type_="unique")
    op.drop_column("tender_lots", "folder_path")

    op.create_table(
        "tender_lot_positions",
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("folder_path", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
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
            ["lot_id"],
            ["tender_lots.id"],
            name=op.f("fk_tender_lot_positions_lot_id_tender_lots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_tender_lot_positions_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_lot_positions")),
        sa.UniqueConstraint(
            "organization_id", "folder_path", "title", name="organization_position"
        ),
    )
    op.create_index(
        op.f("ix_tender_lot_positions_lot_id"), "tender_lot_positions", ["lot_id"], unique=False
    )
    op.create_index(
        op.f("ix_tender_lot_positions_organization_id"),
        "tender_lot_positions",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_tender_lot_positions_organization_id"), table_name="tender_lot_positions"
    )
    op.drop_index(op.f("ix_tender_lot_positions_lot_id"), table_name="tender_lot_positions")
    op.drop_table("tender_lot_positions")
    op.add_column(
        "tender_lots",
        sa.Column("folder_path", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.create_unique_constraint(
        "organization_folder", "tender_lots", ["organization_id", "folder_path"]
    )
