/**
 * Плотная таблица рабочего списка.
 *
 * Сделана похожей на лист Excel намеренно, и не ради красоты: сотрудник
 * половину дня проводит в книге, и переучиваться на другой способ читать те же
 * данные ему незачем. Отсюда всё остальное — шапка не уезжает при прокрутке,
 * первая колонка держится на месте, числа прижаты вправо и набраны цифрами
 * одной ширины, сортировка по щелчку в заголовок.
 *
 * Колонки приходят с сервера вместе с данными. Здесь их состав не решается:
 * его задаёт книга того же проекта, и разойтись они не должны.
 */

import { useMemo, useState } from "react";
import type {
  ColumnSet,
  Worklist,
  WorklistCell,
  WorklistColumn,
  WorklistRow,
} from "@/api/worklist";
import { cx } from "@/ui";
import { verdictLookup } from "./verdicts";
import { ColumnFilterButton } from "./ColumnFilter";
import type { ColumnFilter, FilterState, Filterable } from "./filters";
import { formatDate, formatValue, urgency } from "./format";

type Direction = "asc" | "desc";

/**
 * Заливка строки по вердикту.
 *
 * Цвет всегда дублируется словом: вердикт стоит первой колонкой текстом.
 * Сам по себе он смысла не несёт — при дальтонизме «участвовать» и «не
 * участвовать» неразличимы.
 */
/** Заливка отмеченной ячейки. Насыщеннее строчной: строка красится вердиктом
 *  бледно, и отметка на её фоне должна читаться, а не сливаться. */
const CELL_TONES: Record<string, string> = {
  critical: "bg-critical/25",
  warning: "bg-warning/25",
  good: "bg-good/20",
  info: "bg-series-1/15",
  "": "",
};

const TONES: Record<string, string> = {
  good: "bg-good/10 hover:bg-good/15",
  warning: "bg-warning/10 hover:bg-warning/15",
  info: "bg-series-1/5 hover:bg-series-1/10",
  critical: "bg-critical/5 hover:bg-critical/10",
  "": "hover:bg-plane",
};

export function WorkTable({
  data,
  rows: given,
  columns,
  onOpen,
  openId,
  filters,
  targets,
  onFilter,
}: {
  data: Worklist;
  /** Уже отобранные строки. Отбор считает страница: по нему же строятся
   *  легенда и итог, и делать это в трёх местах значит однажды разойтись. */
  rows: WorklistRow[];
  columns: ColumnSet;
  /** Открыть разбор строки. */
  onOpen: (id: string) => void;
  /** Какая строка сейчас открыта — её видно в списке, чтобы не потеряться. */
  openId: string | null;
  /** Что сейчас отобрано по колонкам. */
  filters: FilterState;
  /** Какие колонки вообще можно отобрать и каким способом. */
  targets: Map<string, Filterable>;
  onFilter: (key: string, next: ColumnFilter | null) => void;
}) {
  // Слово вердикта — из легенды этого раздела, а не из списка в браузере:
  // площадка говорит «участвовать», тендерный отбор «брать».
  const verdict = useMemo(() => verdictLookup(data.legend), [data.legend]);

  const [sort, setSort] = useState<{
    index: number;
    direction: Direction;
  } | null>(null);

  // Колонки отбираются здесь, а не запросом: ответ уже содержит все, и
  // переключение «Главное / Все колонки» получается мгновенным. Индекс
  // исходной колонки нужен, чтобы достать её ячейку из строки.
  const shown = useMemo(
    () =>
      data.columns
        .map((column, index) => ({ column, index }))
        .filter(({ column }) => columns === "all" || column.essential),
    [data.columns, columns],
  );

  const rows = useMemo(() => {
    if (!sort) return given;

    // Сортировка не на месте: список принадлежит кэшу запроса, и перемешивать
    // его значит менять то, что покажет следующий рендер.
    return [...given].sort((left, right) => {
      const compared = compare(left.cells[sort.index], right.cells[sort.index]);
      return sort.direction === "asc" ? compared : -compared;
    });
  }, [given, sort]);

  function toggle(index: number) {
    setSort((current) => {
      if (current?.index !== index) return { index, direction: "asc" };
      // Третий щелчок возвращает порядок отбора — тот же, что в книге.
      return current.direction === "asc" ? { index, direction: "desc" } : null;
    });
  }

  if (!rows.length) {
    return (
      <div className="px-5 py-10 text-center text-sm text-ink-muted">
        Под выбранные условия ничего не подходит
      </div>
    );
  }

  return (
    <div
      className="overflow-auto rounded-b-[10px]"
      style={{ maxHeight: "calc(100vh - 340px)" }}
    >
      {/*
        Раскладка фиксированная, ширины — из книги. Без этого длинное название
        заказчика растягивает свою колонку на пол-экрана, и таблица на девятнадцать
        колонок разъезжается до девяти тысяч точек: маржа оказывается за краем,
        а ради неё человек сюда и пришёл.

        `min-w-full` — про широкий монитор. Ширины в книге подобраны под лист
        Excel, и в «Главном» их сумма до края карточки не достаёт: справа от
        даты оставалась пустая полоса, а заливка строки обрывалась на полпути,
        будто таблица недогрузилась. Так таблица берёт ширину из колонок, но
        не меньше карточки, и лишнее место уходит им соразмерно — то есть
        названиям, которым его и не хватает. Когда колонок больше, чем
        помещается, всё как было: ширины из книги и прокрутка вбок.

        Ширину задаёт `table-fixed` по `colgroup`, а не содержимое. Стояло
        `w-max`, и это работало ровно до появления воронок в шапке: они
        добавили заголовкам по десятку точек, ширина поехала за ними, и в
        «Главном» вылезла прокрутка на шесть точек — та самая, ради избавления
        от которой «Где купить» и стал значком.
      */}
      <table className="min-w-full table-fixed border-collapse text-[13px]">
        <colgroup>
          {/* Номер: ширина под три знака плюс поле. Строк на экране до
              восьмисот, и четырёхзначных не бывает. */}
          <col style={{ width: "3.25rem" }} />
          {shown.map(({ column }) => (
            <col key={column.key} style={{ width: width(column) }} />
          ))}
        </colgroup>
        <thead className="sticky top-0 z-20">
          <tr>
            {/* Номер не сортируется: он и есть порядок, в котором строки
                сейчас лежат. Щелчок по нему мог бы значить только «отменить
                сортировку», а это уже есть в самой колонке. */}
            <th
              scope="col"
              className={cx(
                "border-b border-hairline bg-surface px-2.5 py-2",
                "text-xs font-medium text-ink-muted select-none",
                "text-right",
              )}
            >
              №
            </th>
            {shown.map(({ column, index }) => (
              <th
                key={column.key}
                onClick={() => toggle(index)}
                title={`${column.title} — щёлкните, чтобы отсортировать`}
                className={cx(
                  "group/head cursor-pointer border-b border-hairline bg-surface px-2.5 py-2",
                  "text-xs font-medium whitespace-nowrap text-ink-secondary select-none",
                  "hover:text-ink",
                  column.align === "right" ? "text-right" : "text-left",
                )}
              >
                <span className="inline-flex items-center gap-1">
                  {column.sensitive && (
                    <span aria-hidden title="Себестоимость — видна не всем">
                      ₸
                    </span>
                  )}
                  {column.title}
                  <span aria-hidden className="text-ink-muted">
                    {sort?.index === index
                      ? sort.direction === "asc"
                        ? "↑"
                        : "↓"
                      : ""}
                  </span>
                  {targets.has(column.key) && (
                    <ColumnFilterButton
                      target={targets.get(column.key)!}
                      active={filters.get(column.key)}
                      onChange={(next) => onFilter(column.key, next)}
                    />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            /*
              Строка открывает разбор целиком, и она же — то, чем его
              открывают с клавиатуры. Колонки-кнопки «Разбор» больше нет, и
              без `tabIndex` с обработкой Enter раздел стал бы недоступен
              тому, кто работает без мыши.

              Решение подписано в `title` и в `aria-label`: заливка строки
              его показывает, но при дальтонизме цвет сам по себе неразличим,
              а слова колонки в «Главном» нет.
            */
            <tr
              key={row.id || row.cells[0]?.text}
              tabIndex={row.id ? 0 : -1}
              role={row.id ? "button" : undefined}
              aria-label={
                row.id
                  ? `${verdict(row.tone)?.title ?? "Без решения"}: ${row.cells[0]?.text ?? ""}. Открыть разбор`
                  : undefined
              }
              title={verdict(row.tone)?.title}
              onClick={() => row.id && onOpen(row.id)}
              onKeyDown={(event) => {
                if (!row.id) return;
                if (event.key === "Enter" || event.key === " ") {
                  // Пробел иначе прокрутит страницу вместо открытия разбора.
                  event.preventDefault();
                  onOpen(row.id);
                }
              }}
              className={cx(
                "group cursor-pointer",
                TONES[row.tone] ?? TONES[""],
                // Полоса слева у строк одного лота: связь надо видеть при
                // прокрутке, а сортировка их разводит по списку.
                row.lot && "border-l-2 border-l-series-1",
                "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-series-1",
                openId === row.id &&
                  "outline outline-2 -outline-offset-2 outline-series-1",
              )}
            >
              {/* Номер приходит с сервером и посчитан по всему списку. Своё
                  место в отрисовке брать нельзя: им называют строку вслух, а
                  у собеседника другой отбор — и «сорок вторая» у него чужая.
                  Ссылку на строку он всё равно не заменяет, для неё `row.id`:
                  после выгрузки список пересобирается вместе с номерами. */}
              <td className="border-b border-hairline px-2.5 py-1.5 text-right align-top text-ink-muted tabular-nums">
                {row.number}
                {row.lot && <LotMark lot={row.lot} />}
              </td>
              {shown.map(({ column, index }) => (
                <td
                  key={column.key}
                  className={cx(
                    "border-b border-hairline px-2.5 py-1.5 align-top",
                    column.align === "right"
                      ? "text-right whitespace-nowrap"
                      : "text-left",
                    CELL_TONES[row.cells[index]?.tone ?? ""],
                  )}
                >
                  {column.format === "datetime" ? (
                    <Deadline cell={row.cells[index]} />
                  ) : column.compact ? (
                    <Compact cell={row.cells[index]} />
                  ) : (
                    render(row.cells[index], column)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Отметка лота у номера строки.
 *
 * Не украшение и не ссылка. Позиция с заработком в сорок процентов может
 * лежать в лоте, который целиком в минусе: поставить придётся все позиции, и
 * прибыльная одна дела не спасает. Поэтому знак красный именно тогда, когда в
 * минусе лот, а не строка, — и видно это в списке, до того как строку откроют.
 */
function LotMark({ lot }: { lot: NonNullable<WorklistRow["lot"]> }) {
  const убыток = lot.margin_percent !== null && lot.margin_percent <= 0;
  const итог =
    lot.margin_percent === null
      ? "маржа лота не посчитана"
      : `${убыток ? "убыток" : "маржа"} по лоту ${lot.margin_percent}%`;
  return (
    <span
      title={`Лот из ${lot.positions} позиций — ${итог}. Поставить придётся все.`}
      className={cx(
        "mt-0.5 flex items-center justify-end gap-1 text-[10px] leading-none font-medium",
        убыток ? "text-critical" : "text-ink-muted",
      )}
    >
      {/* Звено цепи: знак связи, а не оценки. Оценку несёт цвет и подпись. */}
      <span aria-hidden>⛓</span>
      {lot.positions}
    </span>
  );
}

/**
 * Ширина колонки берётся из книги: там она подобрана под содержимое.
 *
 * Сверху ограничена: в книге «Товар» шириной пятьдесят два знака нормально —
 * там прокручивают вбок и не жалеют места. На экране такая колонка вытесняет
 * за край всё остальное, а длинный текст всё равно виден целиком по наведению.
 */
function width(column: WorklistColumn): string {
  // Колонке-значку ширина из книги не нужна: там она рассчитана на текст,
  // которого здесь нет. Сорок четыре знака под одну стрелку — это маржа,
  // выдавленная за край экрана.
  if (column.compact) return "7ch";
  return `${Math.min(Math.max(column.width, 9), 34)}ch`;
}

function render(cell: WorklistCell | undefined, column?: WorklistColumn) {
  if (!cell) return <span className="text-ink-muted">—</span>;
  const text = formatValue(cell, column?.format);
  if (!text) return <span className="text-ink-muted">—</span>;

  if (cell.link) {
    return (
      <a
        href={cell.link}
        target="_blank"
        rel="noopener noreferrer"
        // Щелчок по ссылке не должен заодно открывать разбор: человек метил
        // на площадку, а получил бы и то и другое.
        onClick={(event) => event.stopPropagation()}
        className="line-clamp-2 text-series-1 underline decoration-series-1/30 underline-offset-2 hover:decoration-series-1"
        title={text}
      >
        {text}
      </a>
    );
  }

  // Длинный текст не рвёт строку таблицы: полностью он показывается по
  // наведению. Расчёт себестоимости — это полсотни символов, и разложить их
  // на три строки значит растянуть весь список втрое.
  return (
    <span className="line-clamp-2 whitespace-pre-line" title={text}>
      {text}
    </span>
  );
}

/**
 * Колонка-значок: есть ли находка и куда по ней идти.
 *
 * В списке от «Где купить» нужен один ответ — нашли или нет — и переход к
 * первоисточнику. Сорок четыре знака про поставщика, срок и минимальную
 * партию растягивали строку на три линии и выталкивали маржу за край; целиком
 * они есть в подсказке и в разборе.
 */
function Compact({ cell }: { cell?: WorklistCell }) {
  const text = cell?.text?.trim();
  if (!text) return <span className="text-ink-muted">—</span>;

  // Предупреждение «не тот товар» — самое важное, что о находке можно
  // сказать, и прятать его в подсказку нельзя.
  const wrong = text.startsWith("⚠");

  if (!cell?.link) {
    return (
      <span
        title={text}
        className={cx(wrong ? "text-critical" : "text-ink-secondary")}
      >
        {wrong ? "⚠" : "·"}
      </span>
    );
  }
  return (
    <a
      href={cell.link}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => event.stopPropagation()}
      title={text}
      aria-label={text}
      className={cx(
        "inline-block underline-offset-2 hover:underline",
        wrong ? "text-critical" : "text-series-1",
      )}
    >
      {wrong ? "⚠" : "↗"}
    </a>
  );
}

/** Срок с отметкой срочности: просроченное глаз должен находить сам. */
function Deadline({ cell }: { cell?: WorklistCell }) {
  if (!cell?.text) return <span className="text-ink-muted">—</span>;
  const mark = urgency(cell.text);

  return (
    <span className={cx("whitespace-nowrap", mark?.className)}>
      {formatDate(cell.text)}
      {mark && (
        <span className="ml-1.5 text-[11px] font-medium">{mark.text}</span>
      )}
    </span>
  );
}

function compare(left?: WorklistCell, right?: WorklistCell): number {
  // Пустые всегда внизу, в обе стороны: строка без цены не должна
  // возглавлять список ни по возрастанию, ни по убыванию.
  const leftEmpty = isEmpty(left);
  const rightEmpty = isEmpty(right);
  if (leftEmpty || rightEmpty)
    return leftEmpty && rightEmpty ? 0 : leftEmpty ? 1 : -1;

  if (left!.number != null && right!.number != null)
    return left!.number - right!.number;
  return left!.text.localeCompare(right!.text, "ru");
}

function isEmpty(cell?: WorklistCell): boolean {
  return !cell || (cell.number == null && !cell.text);
}
