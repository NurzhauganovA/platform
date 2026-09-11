"""Сумма, за которую подали заявку.

Подача до сих пор была одним нажатием: лот переводили в «Ждём итоги», и всё,
что о ней оставалось, — время перевода. Сумму участия держали в голове и в
переписке, а спрашивают её ровно тогда, когда итоги пришли: за сколько мы
заходили и насколько промахнулись.

Своя колонка, а не `won_amount`. Это разные величины: наша цена участия и цена
победителя совпадают только когда мы выиграли, и складывать их в одно поле
значит потерять первую в тот день, когда проиграли.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7c4e2f10d93"
down_revision = "a5ba01042440"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lot_cards", sa.Column("bid_amount", sa.Numeric(18, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("lot_cards", "bid_amount")
