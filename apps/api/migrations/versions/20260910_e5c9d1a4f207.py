"""Себестоимость рядом с ценой и «Наш товар» вместо «Наша ТС»

Revision ID: e5c9d1a4f207
Revises: c1a7d5b93e10
Create Date: 2026-09-10 10:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5c9d1a4f207"
down_revision: str | Sequence[str] | None = "c1a7d5b93e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Столбцы таблицы разбора лежат документом в JSONB, а не строками схемы,
    # поэтому и правятся здесь запросом, а не `alter table`. Заготовка нового
    # лота уже с этими столбцами — но уже собранные таблицы её не увидят
    # никогда: пересборка моделью трогает только свои три столбца, а
    # человеческие оставляет как есть. Без этой миграции у половины лотов
    # столбец звался бы «Наша ТС», у половины «Наш товар», и на планёрке
    # выяснялось бы, что это одно и то же.
    op.execute(
        """
        UPDATE spec_sheets
        SET columns = (
            SELECT jsonb_agg(
                CASE WHEN item->>'key' = 'ours'
                     THEN jsonb_set(item, '{title}', '"Наш товар"')
                     ELSE item END
                ORDER BY place
            )
            FROM jsonb_array_elements(columns) WITH ORDINALITY AS parts(item, place)
        )
        WHERE columns @> '[{"key": "ours"}]'
        """
    )

    # Себестоимость встаёт сразу за ценой: заработок считается из разницы, и
    # столбец через один заставлял бы возить глазами по строке.
    op.execute(
        """
        UPDATE spec_sheets
        SET columns = (
            SELECT jsonb_agg(added ORDER BY place, extra)
            FROM (
                SELECT item AS added, place, 0 AS extra
                FROM jsonb_array_elements(columns) WITH ORDINALITY AS parts(item, place)
                UNION ALL
                SELECT
                    '{"key": "cost", "title": "Себес", "width": 100, "filled_by": "hand"}'::jsonb,
                    place,
                    1
                FROM jsonb_array_elements(columns) WITH ORDINALITY AS parts(item, place)
                WHERE item->>'key' = 'price'
            ) AS merged
        )
        WHERE columns @> '[{"key": "price"}]'
          AND NOT columns @> '[{"key": "cost"}]'
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        UPDATE spec_sheets
        SET columns = (
            SELECT COALESCE(jsonb_agg(item ORDER BY place), '[]'::jsonb)
            FROM jsonb_array_elements(columns) WITH ORDINALITY AS parts(item, place)
            WHERE item->>'key' <> 'cost'
        )
        WHERE columns @> '[{"key": "cost"}]'
        """
    )
    op.execute(
        """
        UPDATE spec_sheets
        SET columns = (
            SELECT jsonb_agg(
                CASE WHEN item->>'key' = 'ours'
                     THEN jsonb_set(item, '{title}', '"Наша ТС"')
                     ELSE item END
                ORDER BY place
            )
            FROM jsonb_array_elements(columns) WITH ORDINALITY AS parts(item, place)
        )
        WHERE columns @> '[{"key": "ours"}]'
        """
    )
