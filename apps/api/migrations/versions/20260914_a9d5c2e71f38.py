"""Вместо «Себес» в разборе — «Наш ТС».

Себестоимость стояла рядом с ценой ради заработка из разницы, но заполнять её
оказалось нечем: цены поставщиков платформа по госзакупкам не знает, а
снабжение работает в своей копии таблицы. Столбец стоял пустым во всех
разборах и занимал место, которого таблице и так не хватает.

На его месте «Наш ТС» — чем наше предложение отвечает требованию заказчика.
Рядом с «Наш товар» это два разных вопроса: первый «что предлагаем», второй
«подходит ли», и сверяют их со спецификацией строка за строкой.

Значения из «Себес» не переносятся: переносить нечего — это другая величина, и
в тех редких строках, где цифра стояла, она означала закупочную цену, а не
характеристику. Ячейки удаляются вместе со столбцом.
"""

from __future__ import annotations

from alembic import op

revision = "a9d5c2e71f38"
down_revision = "f2b6a90d47e3"
branch_labels = None
depends_on = None

НОВЫЙ = '{"key": "our_spec", "title": "Наш ТС", "width": 300, "filled_by": "hand"}'


def upgrade() -> None:
    # Столбец «Себес» убираем из описания таблиц, а «Наш ТС» дописываем в
    # конец — там же, где он стоит у новых разборов.
    op.execute(
        f"""
        update spec_sheets
        set columns = (
            select coalesce(jsonb_agg(item), '[]'::jsonb) || '{НОВЫЙ}'::jsonb
            from jsonb_array_elements(columns) as item
            where item->>'key' <> 'cost'
        )
        where columns @> '[{{"key": "cost"}}]'::jsonb
        """
    )
    # И сами значения: ячейка без столбца не показывается, но лежит в строке и
    # уезжает в ответ API на каждое открытие вкладки.
    op.execute(
        """
        update spec_sheets
        set rows = (
            select coalesce(jsonb_agg(
                jsonb_set(row_item, '{cells}', (row_item->'cells') - 'cost')
            ), '[]'::jsonb)
            from jsonb_array_elements(rows) as row_item
        )
        where rows::text like '%"cost"%'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        update spec_sheets
        set columns = (
            select coalesce(jsonb_agg(item), '[]'::jsonb)
                || '{"key": "cost", "title": "Себес", "width": 100, "filled_by": "hand"}'::jsonb
            from jsonb_array_elements(columns) as item
            where item->>'key' <> 'our_spec'
        )
        where columns @> '[{"key": "our_spec"}]'::jsonb
        """
    )
