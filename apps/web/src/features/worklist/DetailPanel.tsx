/**
 * Разбор одной строки — панель сбоку.
 *
 * Панель, а не отдельная страница, и это выбор в пользу работы. Тендерщик
 * проходит список сверху вниз и заглядывает в разбор десятки раз подряд;
 * переход на страницу каждый раз терял бы прокрутку, отбор и сортировку, а
 * возвращаться пришлось бы кнопкой «назад».
 *
 * Содержимое собирает сервер: разделы, их порядок и оговорки приходят готовыми
 * и повторяют лист разбора в книге. Здесь только вёрстка — решать, что
 * показать, значит завести второй источник правды.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  worklists,
  type DetailField,
  type DetailSection,
  type WorklistSlug,
} from "@/api/worklist";
import { Badge, Spinner, cx } from "@/ui";
import { formatValue } from "./format";
import { GLYPH, GLYPH_COLOR } from "./verdicts";
import { MIN_WIDTH, maxWidth, usePanelWidth } from "./usePanelWidth";

const FIELD_TONE: Record<string, string> = {
  good: "text-good",
  warning: "text-warning",
  critical: "text-critical",
  "": "text-ink",
};

export function DetailPanel({
  slug,
  id,
  onClose,
}: {
  slug: WorklistSlug;
  id: string;
  onClose: () => void;
}) {
  // Какую находку человек выбрал для расчёта. Живёт здесь, а не в адресе:
  // это примерка «а если брать у этого», а не состояние, которым делятся, —
  // и сбрасывается вместе со сменой строки.
  const [pick, setPick] = useState("");
  useEffect(() => setPick(""), [id]);

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: [slug, "detail", id, pick],
    queryFn: () => worklists.detail(slug, id, pick),
    // Прошлый расчёт остаётся на экране, пока считается новый: иначе панель
    // мигает пустотой на каждый выбор поставщика.
    placeholderData: (previous) => previous,
  });

  const panel = usePanelWidth();

  // Escape закрывает — в панели, которую открывают десятки раз за час, тянуться
  // мышью к крестику каждый раз утомительно.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 z-40 bg-ink/20"
        aria-hidden
      />
      <aside
        role="dialog"
        aria-label="Разбор"
        style={{ width: panel.width, maxWidth: "100vw" }}
        className={cx(
          "fixed top-0 right-0 z-50 flex h-full flex-col border-l border-hairline bg-surface shadow-2xl",
          // Пока тянут — без плавности: анимированная ширина отстаёт от
          // курсора, и панель едет за рукой с задержкой.
          !panel.dragging && "transition-[width] duration-150",
        )}
      >
        <ResizeHandle panel={panel} />
        <header className="flex items-start justify-between gap-4 border-b border-hairline px-6 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {data?.tone && (
                <span
                  className={cx(
                    "text-base leading-none",
                    GLYPH_COLOR[data.tone],
                  )}
                >
                  {GLYPH[data.tone]}
                </span>
              )}
              <h2 className="truncate text-base font-semibold text-ink">
                {data?.title ?? "Разбор"}
              </h2>
            </div>
            {data?.subtitle && (
              <p className="mt-0.5 truncate text-sm text-ink-muted">
                {data.subtitle}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {data?.url && (
              <a
                href={data.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
              >
                На площадке ↗
              </a>
            )}
            <button
              onClick={onClose}
              aria-label="Закрыть"
              title="Закрыть (Esc)"
              className="rounded-[8px] px-2.5 py-1.5 text-sm text-ink-muted transition hover:bg-plane hover:text-ink"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <Spinner label="Собираем разбор…" />
          ) : isError ? (
            <p className="text-sm text-ink-muted">
              {error instanceof Error ? error.message : "Разбор не собрался"}
            </p>
          ) : data ? (
            <div className="space-y-6">
              {data.verdict && (
                <Badge tone={data.tone || "neutral"}>
                  {data.tone && GLYPH[data.tone]} {data.verdict}
                </Badge>
              )}
              {data.sections.map((section) => (
                <SectionBlock
                  key={section.title}
                  section={section}
                  onPick={setPick}
                  busy={isFetching}
                />
              ))}
              {data.hidden_sections > 0 && (
                <p className="border-t border-hairline pt-4 text-xs text-ink-muted">
                  Ещё {data.hidden_sections}{" "}
                  {data.hidden_sections === 1 ? "раздел" : "раздела"} с
                  себестоимостью и маржой — их видит тендерщик.
                </p>
              )}
            </div>
          ) : null}
        </div>
      </aside>
    </>
  );
}

/**
 * Ручка на левой стенке: тянут — панель шире.
 *
 * Посередине по высоте, а не по всему краю: за середину тянут не глядя, и
 * рука находит её тем же движением, что край окна. Полоса захвата шире
 * видимой чёрточки — в шесть точек попадают не с первого раза.
 *
 * `separator` с `aria-valuenow` — не формальность: озвучка читает её как
 * «разделитель, 672 из 1400», и стрелками ширину меняет тот, кто не работает
 * мышью. Без этого панель настраивалась бы только курсором.
 */
function ResizeHandle({ panel }: { panel: ReturnType<typeof usePanelWidth> }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Ширина разбора: тяните или меняйте стрелками"
      aria-valuenow={Math.round(panel.width)}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={maxWidth(window.innerWidth)}
      tabIndex={0}
      onPointerDown={panel.onPointerDown}
      onKeyDown={panel.onKeyDown}
      onDoubleClick={panel.onDoubleClick}
      title="Тяните, чтобы изменить ширину. Двойной щелчок — вернуть исходную"
      className={cx(
        // Полоса захвата во всю высоту: попасть в неё легче, чем в саму
        // заготовку, а тянуть удобно с любой высоты. Видимый знак при этом
        // один и посередине — вертикальная линия во весь край спорила бы с
        // содержимым, ради которого панель и открывают.
        "group absolute top-0 left-0 z-10 flex h-full w-4 -translate-x-1/2 cursor-col-resize",
        "items-center justify-center focus:outline-none",
      )}
    >
      {/*
        Видимая заготовка, а не бледная чёрточка. Курсор `col-resize`
        появляется только над самой ручкой, а чтобы навести на неё мышь, надо
        сперва знать, что она там есть: невидимая полоса — это возможность,
        о которой никто не узнает. Точки — общепринятый знак «за это тянут»,
        и читаются они без цвета.
      */}
      <span
        aria-hidden
        className={cx(
          "flex h-12 w-4 items-center justify-center rounded-full border bg-surface text-[10px] leading-none tracking-tighter shadow-sm transition",
          panel.dragging
            ? "border-series-1 text-series-1"
            : "border-hairline text-ink-muted group-hover:border-series-1 group-hover:text-series-1 group-focus-visible:border-series-1 group-focus-visible:text-series-1",
        )}
      >
        ⋮⋮
      </span>
    </div>
  );
}

function SectionBlock({
  section,
  onPick,
  busy,
}: {
  section: DetailSection;
  /** Выбрать находку для пересчёта себестоимости. */
  onPick?: (key: string) => void;
  busy?: boolean;
}) {
  const empty = !section.fields.length && !section.table;
  const count = section.fields.length + (section.table?.rows.length ?? 0);

  // Свёрнутость решает сервер, но дальше ей распоряжается человек: раскрыл —
  // осталось раскрытым, пока не свернёт обратно. Пустой раздел не сворачиваем
  // никогда: под заголовком «Конкуренты (0)» человек ищет то, чего нет.
  const [open, setOpen] = useState(!section.collapsed || empty);
  const foldable = section.collapsed && !empty;

  const heading = (
    <>
      {section.title}
      {foldable && <span className="ml-1.5 tabular-nums">({count})</span>}
    </>
  );

  return (
    <section>
      {foldable ? (
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="mb-2 flex w-full items-center gap-1.5 text-[11px] font-semibold tracking-wide text-ink-muted uppercase transition hover:text-ink"
        >
          {/* Треугольник, а не только цвет и положение: состояние «свёрнут»
              должно читаться и в чёрно-белой распечатке. */}
          <span
            aria-hidden
            className={cx(
              "inline-block transition-transform",
              open && "rotate-90",
            )}
          >
            ▸
          </span>
          <h3>{heading}</h3>
        </button>
      ) : (
        <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-ink-muted uppercase">
          {heading}
        </h3>
      )}

      {!open ? null : empty ? (
        <p className="text-sm text-ink-muted">
          {section.empty || "Нет данных"}
        </p>
      ) : (
        <>
          {section.fields.length > 0 && (
            <dl className="divide-y divide-hairline rounded-[8px] border border-hairline">
              {section.fields.map((field, index) => (
                <FieldRow key={`${field.label}-${index}`} field={field} />
              ))}
            </dl>
          )}
          {section.table && (
            <MiniTable table={section.table} onPick={onPick} busy={busy} />
          )}
        </>
      )}

      {open && section.note && (
        <p className="mt-2 text-xs text-ink-muted">{section.note}</p>
      )}
    </section>
  );
}

function FieldRow({ field }: { field: DetailField }) {
  const value = formatValue(field, field.format);

  // Без подписи — это замечание, а не поле: перед подачей их выводят списком.
  if (!field.label) {
    return (
      <div className="flex gap-2 px-3.5 py-2.5">
        <span aria-hidden className={cx("shrink-0", FIELD_TONE[field.tone])}>
          {field.tone === "good" ? "✓" : field.tone === "critical" ? "✕" : "▲"}
        </span>
        <span className="text-sm text-ink">{field.text}</span>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[minmax(0,11rem)_1fr] gap-3 px-3.5 py-2 text-sm">
      <dt className="text-ink-muted">{field.label}</dt>
      <dd
        className={cx(
          "min-w-0 break-words",
          FIELD_TONE[field.tone] ?? "text-ink",
        )}
      >
        {field.link ? (
          <a
            href={field.link}
            target="_blank"
            rel="noopener noreferrer"
            className="text-series-1 underline decoration-series-1/30 underline-offset-2 hover:decoration-series-1"
          >
            {value}
          </a>
        ) : (
          value
        )}
        {field.note && (
          <div className="mt-0.5 text-xs text-ink-muted">{field.note}</div>
        )}
      </dd>
    </div>
  );
}

/**
 * Маленькая таблица внутри раздела.
 *
 * Строка бывает трёх видов, и все три встречаются в «Где купить»:
 *
 * - **со ссылкой** — ведёт на карточку товара. Находка без ссылки это
 *   обещание, а не поставщик: менеджер пойдёт искать её заново поиском и
 *   половину не найдёт.
 * - **выбираемая** — по ней можно пересчитать себестоимость. Ядро берёт самую
 *   дешёвую из подходящих, но «подходит» — суждение модели, а поставщик может
 *   быть незнакомым. Считает пересчёт всё равно сервер.
 * - **отмеченная** — та, по которой себестоимость посчитана сейчас. Без
 *   отметки непонятно, откуда взялась цифра.
 */
function MiniTable({
  table,
  onPick,
  busy,
}: {
  table: NonNullable<DetailSection["table"]>;
  onPick?: (key: string) => void;
  busy?: boolean;
}) {
  const chosen = new Set(table.chosen ?? []);
  const pickable = Boolean(onPick && table.picks?.some(Boolean));

  return (
    <div className="overflow-x-auto rounded-[8px] border border-hairline">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-hairline text-left text-xs text-ink-muted">
            {pickable && <th className="w-8 px-2 py-1.5 font-medium" />}
            {/* Номер: находок на позицию бывает под сотню, и назвать нужную
                вслух («возьми четвёртую») иначе нечем — названия у них
                похожи до неразличимости. */}
            <th className="w-10 px-2 py-1.5 text-right font-medium">№</th>
            {table.columns.map((title, index) => (
              <th
                key={title}
                className={cx(
                  "px-3 py-1.5 font-medium",
                  table.aligns[index] === "right" && "text-right",
                )}
              >
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => {
            const link = table.links?.[rowIndex] || "";
            const pick = table.picks?.[rowIndex] || "";
            const active = pick !== "" && chosen.has(pick);
            return (
              <tr
                key={rowIndex}
                className={cx(
                  "border-b border-hairline last:border-0",
                  active && "bg-series-1/8",
                  pick && onPick && !active && "hover:bg-plane",
                )}
              >
                <td className="px-2 py-1.5 text-right align-top text-ink-muted tabular-nums">
                  {rowIndex + 1}
                </td>
                {pickable && (
                  <td className="px-2 py-1.5 align-top">
                    {pick ? (
                      <button
                        type="button"
                        onClick={() => !busy && onPick?.(pick)}
                        disabled={busy}
                        aria-pressed={active}
                        title={
                          active
                            ? "По этой находке посчитана себестоимость"
                            : "Считать себестоимость по этой находке"
                        }
                        className={cx(
                          "flex h-4 w-4 items-center justify-center rounded-full border text-[10px] leading-none transition",
                          active
                            ? "border-series-1 bg-series-1 text-white"
                            : "border-baseline text-transparent hover:border-series-1",
                          busy && "opacity-50",
                        )}
                      >
                        {/* Галочка, а не только заливка: отметка должна
                            читаться и без цвета. */}
                        ✓
                      </button>
                    ) : null}
                  </td>
                )}
                {row.map((cell, index) => (
                  <td
                    key={index}
                    className={cx(
                      "px-3 py-1.5 text-ink",
                      table.aligns[index] === "right" &&
                        "text-right whitespace-nowrap",
                    )}
                  >
                    {index === (table.link_column ?? 0) && link ? (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(event) => event.stopPropagation()}
                        className="text-series-1 underline decoration-series-1/30 underline-offset-2 hover:decoration-series-1"
                      >
                        {cell || "—"} ↗
                      </a>
                    ) : (
                      cell || "—"
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
