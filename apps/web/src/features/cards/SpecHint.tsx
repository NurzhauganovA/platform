/**
 * Требования заказчика под текстом замечания — чтобы не ходить за ними во
 * вкладку.
 *
 * Замечание пишут ровно про них: «требуете процессор не ниже конкретной
 * модели» — это довод, и чтобы его написать, требование надо видеть дословно.
 * Пока таблица жила только во вкладке «Разбор», человек переключался туда,
 * запоминал абзац, возвращался и писал по памяти — а память округляет «не
 * менее 4.5 ГГц» до «около 4.5».
 *
 * Складкой в подвале блока, а не отдельной карточкой. Своей рамкой она читалась
 * как ещё один документ на вкладке, хотя это подсказка к тому, что написано
 * выше. Свёрнута по умолчанию: у системного блока в сборе двенадцать предметов,
 * и развёрнутая таблица уводит текст замечания за край экрана.
 *
 * Два столбца из всей таблицы: предмет и требование. Выжимка, марка и цена
 * здесь лишние — их пишет снабжение под подбор товара, а в обращении к
 * заказчику ссылаться на нашу предполагаемую цену нельзя вовсе.
 *
 * Только чтение. Править таблицу можно во вкладке «Разбор»: два редактора
 * одного документа на одном экране означают, что правки одного затирают
 * правки другого, а заметно это станет через неделю.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { sheetApi, type Card } from "@/api/cards";
import { Spinner, cx } from "@/ui";
import { Chevron } from "./kit";

/** Ключи столбцов модели. Те же, что объявляет сервер. */
const SUBJECT = "subject";
const DEMAND = "demand";

export function SpecHint({ card }: { card: Card }) {
  const [open, setOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["card", card.id, "sheet"],
    queryFn: () => sheetApi.get(card.id),
    staleTime: 30_000,
    enabled: open,
  });

  const rows = (data?.rows ?? []).filter(
    (row) => (row.cells[DEMAND] ?? "").trim() !== "",
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className={cx(
          "flex w-full items-center gap-2 border-t border-hairline/70 px-[15px] py-[11px]",
          "text-left transition hover:bg-plane/60",
          "focus-visible:outline focus-visible:outline-2",
          "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
        )}
      >
        <Chevron open={open} />
        <span className="text-[13.5px] font-semibold tracking-[-0.01em] text-ink">
          Требования заказчика
        </span>
        <span className="min-w-0 flex-1 truncate text-[11.5px] text-ink-muted">
          {open
            ? "из технической спецификации, дословно"
            : "разбор спецификации, чтобы писать замечание не уходя со страницы"}
        </span>
        {data && rows.length > 0 && (
          <span className="text-[11.5px] text-ink-muted tabular-nums">
            {rows.length}
          </span>
        )}
      </button>

      {open && (
        <div className="px-[15px] pb-3">
          {isLoading ? (
            <div className="py-2">
              <Spinner label="Читаем разбор…" />
            </div>
          ) : rows.length === 0 ? (
            <p className="py-2 text-[12.5px] text-ink-muted">
              Спецификация ещё не разобрана. Откройте вкладку «Разбор» и нажмите
              «Разобрать спецификацию» — требования появятся здесь.
            </p>
          ) : (
            /* Своя высота с прокруткой: у системного блока в сборе двенадцать
               предметов, и развёрнутый список уводит текст замечания за край
               экрана — ровно то, ради чего складку сюда и поставили. */
            <div className="max-h-80 overflow-y-auto">
              {rows.map((row, index) => (
                <div
                  key={row.key}
                  className="flex gap-2.5 border-t border-hairline/70 py-2"
                >
                  <span className="w-[18px] shrink-0 text-[11.5px] text-ink-muted tabular-nums">
                    {index + 1}
                  </span>
                  <span className="w-[120px] shrink-0 text-[12.5px] text-ink">
                    {row.cells[SUBJECT] || "—"}
                  </span>
                  <span className="min-w-0 flex-1 text-[12.5px] leading-[1.55] whitespace-pre-line text-ink-secondary">
                    {row.cells[DEMAND]}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
