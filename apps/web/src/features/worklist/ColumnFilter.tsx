/**
 * Фильтр в шапке колонки — как автофильтр Excel.
 *
 * Открывается значком воронки, а не отдельной панелью сбоку: фильтр стоит
 * там, где данные, и человек не ищет, куда его положили. Тот же жест он
 * делает в книге двадцать раз на дню.
 *
 * У текстовой колонки — список значений с числом строк и поиском по нему; у
 * числовой и денежной — «от» и «до» с настоящими границами данных в
 * подсказках; у даты — период. Вид определяется форматом колонки, а не её
 * названием: раздел, который добавят следующим, получит фильтры сам.
 *
 * Список рисуется поверх страницы, а не внутри шапки, и это не украшение.
 * Таблица прокручивается внутри своего окна (`overflow-auto` с ограничением
 * по высоте), и всё, что вылезает за него, обрезается: до нижних значений
 * категории было не добраться вовсе. Поэтому положение считается от кнопки и
 * задаётся в координатах экрана, а при нехватке места снизу список
 * разворачивается вверх.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ColumnFilter as Filter, Filterable } from "./filters";
import { BLANK } from "./filters";
import { cx } from "@/ui";

export function ColumnFilterButton({
  target,
  active,
  onChange,
}: {
  target: Filterable;
  active: Filter | undefined;
  onChange: (next: Filter | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number; maxHeight: number } | null>(null);

  const WIDTH = 288;
  const GAP = 6;
  const EDGE = 12;

  /** Куда положить список, чтобы он поместился на экране целиком. */
  const locate = useCallback(() => {
    const button = anchor.current?.getBoundingClientRect();
    if (!button) return;
    const below = window.innerHeight - button.bottom - GAP - EDGE;
    const above = button.top - GAP - EDGE;
    // Разворачиваем вверх, когда снизу тесно: у нижних строк таблицы места
    // под списком нет вовсе, и без разворота он схлопывался бы в полоску.
    const upward = below < 240 && above > below;
    setPlace({
      left: Math.min(Math.max(EDGE, button.left), window.innerWidth - WIDTH - EDGE),
      top: upward ? Math.max(EDGE, button.top - GAP) : button.bottom + GAP,
      maxHeight: Math.max(180, upward ? above : below),
    });
  }, []);

  useLayoutEffect(() => {
    if (open) locate();
  }, [open, locate]);

  // Закрываем по щелчку мимо и по Esc; при прокрутке и смене размера окна
  // список едет за своей кнопкой — иначе он остаётся висеть в стороне.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!anchor.current?.contains(target) && !panel.current?.contains(target)) {
        setOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        anchor.current?.focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", locate);
    window.addEventListener("scroll", locate, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", locate);
      window.removeEventListener("scroll", locate, true);
    };
  }, [open, locate]);

  const dropdown = open && place && (
    <div
      ref={panel}
      onClick={(event) => event.stopPropagation()}
      style={{
        left: place.left,
        top: place.top,
        width: WIDTH,
        maxHeight: place.maxHeight,
        // Вверх — значит нижним краем к кнопке.
        transform: place.top < (anchor.current?.getBoundingClientRect().top ?? 0)
          ? "translateY(-100%)"
          : undefined,
      }}
      className="fixed z-50 flex flex-col overflow-hidden rounded-[10px] border border-baseline bg-surface p-3 text-left shadow-xl"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="truncate text-xs font-semibold text-ink">
          {target.column.title}
        </span>
        {active && (
          <button
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className="shrink-0 text-xs text-ink-muted underline underline-offset-2 hover:text-ink"
          >
            сбросить
          </button>
        )}
      </div>

      {target.kind === "values" ? (
        <ValueList target={target} active={active} onChange={onChange} />
      ) : (
        <RangeInputs
          target={target}
          active={active}
          onChange={onChange}
          onDone={() => setOpen(false)}
        />
      )}
    </div>
  );

  return (
    <span className="inline-flex">
      <button
        ref={anchor}
        type="button"
        onClick={(event) => {
          // Иначе щелчок дойдёт до заголовка и заодно пересортирует таблицу.
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        aria-label={`Отбор по колонке «${target.column.title}»`}
        aria-expanded={open}
        title={
          active
            ? `Отбор по «${target.column.title}» включён`
            : `Отобрать по «${target.column.title}»`
        }
        // Видна всегда, как в Excel. Появляться по наведению — значит
        // спрятать возможность от того, кто не знает, что она есть: курсор
        // по шапке просто так не водят.
        className={cx(
          "rounded-[4px] px-1 leading-none transition",
          active ? "text-series-1" : "text-ink-muted/60 hover:text-ink",
        )}
      >
        {/* Заполненная воронка — фильтр стоит, пустая — нет. Не только цвет:
            при дальтонизме включённый и выключенный неразличимы. */}
        {active ? "▼" : "▽"}
      </button>

      {dropdown && createPortal(dropdown, document.body)}
    </span>
  );
}

function ValueList({
  target,
  active,
  onChange,
}: {
  target: Filterable;
  active: Filter | undefined;
  onChange: (next: Filter | null) => void;
}) {
  const [needle, setNeedle] = useState("");
  const chosen = active?.kind === "values" ? active.values : new Set<string>();

  const shown = useMemo(() => {
    const text = needle.trim().toLowerCase();
    if (!text) return target.options;
    return target.options.filter((item) => item.value.toLowerCase().includes(text));
  }, [target.options, needle]);

  function toggle(value: string) {
    const next = new Set(chosen);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onChange(next.size ? { kind: "values", values: next } : null);
  }

  return (
    // Поле поиска и нижняя строка остаются на месте, прокручивается только
    // список: иначе «выбрать всё» уезжает за нижний край вместе с ним.
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Поиск появляется, когда значений столько, что глазами не находишь. */}
      {target.options.length > 8 && (
        <input
          value={needle}
          onChange={(event) => setNeedle(event.target.value)}
          placeholder="Найти значение…"
          className="mb-2 w-full rounded-[6px] border border-baseline bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-muted"
        />
      )}

      {/* Высота — сколько дал список сверху, а не фиксированные шестнадцать
          строк: у нижних строк таблицы места меньше, и жёсткая высота
          прятала последние значения под краем экрана. */}
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {shown.length === 0 && (
          <p className="px-1 py-2 text-xs text-ink-muted">Ничего не нашлось</p>
        )}
        {shown.map((item) => (
          <label
            key={item.value}
            className="flex cursor-pointer items-center gap-2 rounded-[6px] px-1 py-1 text-xs hover:bg-plane"
          >
            <input
              type="checkbox"
              checked={chosen.has(item.value)}
              onChange={() => toggle(item.value)}
              className="shrink-0"
            />
            <span
              className={cx(
                "min-w-0 flex-1 truncate",
                item.value === BLANK ? "text-ink-muted italic" : "text-ink",
              )}
            >
              {item.value}
            </span>
            <span className="shrink-0 tabular-nums text-ink-muted">{item.count}</span>
          </label>
        ))}
      </div>

      {shown.length > 1 && (
        <div className="mt-2 flex gap-3 border-t border-hairline pt-2 text-xs">
          <button
            onClick={() =>
              onChange({ kind: "values", values: new Set(shown.map((item) => item.value)) })
            }
            className="text-ink-muted underline underline-offset-2 hover:text-ink"
          >
            выбрать всё{needle && " найденное"}
          </button>
          {chosen.size > 0 && (
            <button
              onClick={() => onChange(null)}
              className="text-ink-muted underline underline-offset-2 hover:text-ink"
            >
              снять
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function RangeInputs({
  target,
  active,
  onChange,
  onDone,
}: {
  target: Filterable;
  active: Filter | undefined;
  onChange: (next: Filter | null) => void;
  onDone: () => void;
}) {
  const range = active?.kind === "range" ? active : { min: null, max: null };
  const dates = target.column.format === "datetime";

  const toField = (value: number | null) => {
    if (value == null) return "";
    return dates ? new Date(value).toISOString().slice(0, 10) : String(value);
  };
  const fromField = (raw: string): number | null => {
    if (!raw) return null;
    const value = dates ? Date.parse(raw) : Number(raw);
    return Number.isFinite(value) ? value : null;
  };

  function set(edge: "min" | "max", raw: string) {
    const next = { kind: "range" as const, ...range, [edge]: fromField(raw) };
    onChange(next.min == null && next.max == null ? null : next);
  }

  const hint = (value: number) =>
    dates
      ? new Date(value).toLocaleDateString("ru-RU")
      : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);

  return (
    <>
      <div className="flex items-center gap-2">
        <input
          type={dates ? "date" : "number"}
          value={toField(range.min)}
          onChange={(event) => set("min", event.target.value)}
          placeholder={target.bounds ? `от ${hint(target.bounds.min)}` : "от"}
          className="w-full rounded-[6px] border border-baseline bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-muted"
        />
        <span aria-hidden className="text-ink-muted">
          —
        </span>
        <input
          type={dates ? "date" : "number"}
          value={toField(range.max)}
          onChange={(event) => set("max", event.target.value)}
          placeholder={target.bounds ? `до ${hint(target.bounds.max)}` : "до"}
          className="w-full rounded-[6px] border border-baseline bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-muted"
        />
      </div>

      {/* Готовые пороги: маржа выше двадцати и заработок от миллиона — это
          то, ради чего фильтр открывают чаще всего, и набирать их руками по
          десять раз на дню незачем. Считаются от самих данных, поэтому
          подходят и там, где суммы на два порядка меньше. */}
      {!dates && target.bounds && <Presets target={target} onChange={onChange} />}

      <p className="mt-2 border-t border-hairline pt-2 text-[11px] text-ink-muted">
        Строки, где значения нет, под условие не подходят: неизвестная величина
        — не то же самое, что подходящая.
      </p>
      <button
        onClick={onDone}
        className="mt-2 w-full rounded-[6px] bg-series-1/10 px-2 py-1 text-xs font-medium text-series-1 hover:bg-series-1/15"
      >
        Готово
      </button>
    </>
  );
}

function Presets({
  target,
  onChange,
}: {
  target: Filterable;
  onChange: (next: Filter | null) => void;
}) {
  const bounds = target.bounds!;
  const percent = target.column.format === "percent";

  // У процентов пороги круглые и понятные; у денег — от самих данных, иначе
  // «от миллиона» бессмысленно там, где вся закупка на двести тысяч.
  const steps = percent
    ? [10, 20, 30, 50]
    : [0.25, 0.5, 0.75].map((share) =>
        Math.round((bounds.min + (bounds.max - bounds.min) * share) / 1000) * 1000,
      );

  const label = (value: number) =>
    percent
      ? `от ${value}%`
      : `от ${new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(value)}`;

  const usable = [...new Set(steps)].filter(
    (value) => value > bounds.min && value < bounds.max,
  );
  if (!usable.length) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {usable.map((value) => (
        <button
          key={value}
          onClick={() => onChange({ kind: "range", min: value, max: null })}
          className="rounded-full border border-hairline px-2 py-0.5 text-[11px] text-ink-secondary transition hover:border-series-1 hover:text-series-1"
        >
          {label(value)}
        </button>
      ))}
    </div>
  );
}
