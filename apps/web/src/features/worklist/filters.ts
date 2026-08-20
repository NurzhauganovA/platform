/**
 * Отбор строк по колонкам — то же, что автофильтр в Excel.
 *
 * Метафора выбрана не случайно. Сотрудник половину дня проводит в книге и уже
 * умеет фильтровать: значок в шапке, список значений с галочками, «от» и «до»
 * у чисел. Свой способ пришлось бы объяснять, а этот он знает.
 *
 * Какие колонки пригодны и каким фильтром — решается по данным, а не списком
 * заголовков. Список заголовков означал бы, что фильтр по категории есть в
 * тендерах и нет на площадке, которую добавят следующей, и никто этого не
 * заметит. Правило вместо списка:
 *
 * - **числа и проценты** — диапазон «от и до». Маржа выше двадцати процентов
 *   и заработок от миллиона — это два вопроса, ради которых фильтры и просят.
 * - **даты** — период.
 * - **текст** — список значений, но только там, где значения повторяются.
 *   «Категория» и «Заказчик» повторяются, «Название закупки» уникально в
 *   каждой строке: список из двухсот шестидесяти пяти пунктов не фильтр, а
 *   способ потерять время. Такие колонки ищутся строкой поиска.
 *
 * Считается всё в браузере: строки уже пришли целиком, и второй запрос ради
 * того, что лежит в памяти вкладки, — это полсекунды на каждое нажатие.
 */

import type { Worklist, WorklistColumn, WorklistRow } from "@/api/worklist";

/** Отбор по одной колонке. */
export type ColumnFilter =
  | { kind: "values"; values: Set<string> }
  | { kind: "range"; min: number | null; max: number | null };

export type FilterState = Map<string, ColumnFilter>;

/** Чем можно отфильтровать колонку и с какими границами. */
export interface Filterable {
  column: WorklistColumn;
  index: number;
  kind: "values" | "range";
  /** Значения с числом строк — для списка с галочками. */
  options: { value: string; count: number }[];
  /** Границы данных — подсказкой в полях «от» и «до». */
  bounds: { min: number; max: number } | null;
}

/** Сколько разных значений ещё имеет смысл показывать списком. */
const MAX_OPTIONS = 400;

/**
 * Доля уникальных значений, выше которой колонка перестаёт быть признаком.
 *
 * У «Названия закупки» уникально почти каждое значение — список из них
 * бесполезен. У «Категории» значений два десятка на триста строк.
 */
const CATEGORICAL = 0.6;

const NUMERIC = new Set(["money", "percent", "quantity"]);

export function filterable(data: Worklist): Filterable[] {
  const result: Filterable[] = [];

  data.columns.forEach((column, index) => {
    if (column.compact) return; // значок вместо текста — фильтровать нечего

    if (NUMERIC.has(column.format)) {
      const numbers = data.rows
        .map((row) => row.cells[index]?.number)
        .filter((value): value is number => value != null);
      // Одно значение на все строки — фильтр, который ничего не делит.
      if (new Set(numbers).size < 2) return;
      result.push({
        column,
        index,
        kind: "range",
        options: [],
        bounds: { min: Math.min(...numbers), max: Math.max(...numbers) },
      });
      return;
    }

    if (column.format === "datetime") {
      const times = data.rows
        .map((row) => Date.parse(row.cells[index]?.text ?? ""))
        .filter((value) => Number.isFinite(value));
      if (new Set(times).size < 2) return;
      result.push({
        column,
        index,
        kind: "range",
        options: [],
        bounds: { min: Math.min(...times), max: Math.max(...times) },
      });
      return;
    }

    const counts = new Map<string, number>();
    for (const row of data.rows) {
      const text = row.cells[index]?.text?.trim() ?? "";
      counts.set(text, (counts.get(text) ?? 0) + 1);
    }
    const distinct = counts.size;
    if (distinct < 2 || distinct > MAX_OPTIONS) return;
    if (distinct > data.rows.length * CATEGORICAL) return;

    result.push({
      column,
      index,
      kind: "values",
      options: [...counts.entries()]
        .map(([value, count]) => ({ value: value || "— пусто —", count }))
        .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value, "ru")),
      bounds: null,
    });
  });

  return result;
}

/** Пустое значение показывается словами: «— пусто —» отличимо от пробела. */
export const BLANK = "— пусто —";

/**
 * Сколько строк за каждым значением колонки.
 *
 * Считается отдельно от `filterable`, потому что считать надо по другому
 * набору строк. Список значений в фильтре берётся до отбора — иначе снятое
 * значение исчезло бы и вернуть его было бы нечем, — а числа рядом с ними
 * должны учитывать соседние фильтры: выбрал категорию «Электроника», и
 * напротив заказчиков стоит, сколько их электроники, а не сколько всего.
 */
export function countValues(rows: WorklistRow[], index: number): Map<string, number> {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const value = row.cells[index]?.text?.trim() || BLANK;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}

/** Тот же фильтр, но без условия по одной колонке. */
export function without(state: FilterState, key: string): FilterState {
  const rest = new Map(state);
  rest.delete(key);
  return rest;
}

export function apply(
  rows: WorklistRow[],
  columns: WorklistColumn[],
  state: FilterState,
): WorklistRow[] {
  if (!state.size) return rows;

  // Условия раскладываются один раз, а не на каждую строку: при трёхстах
  // строках и пяти фильтрах разница между разом и полутора тысячами.
  const checks: ((row: WorklistRow) => boolean)[] = [];
  for (const [key, filter] of state) {
    const index = columns.findIndex((column) => column.key === key);
    if (index < 0) continue; // колонка скрыта правами или составом
    const column = columns[index];

    if (filter.kind === "values") {
      const wanted = filter.values;
      checks.push((row) => wanted.has(row.cells[index]?.text?.trim() || BLANK));
      continue;
    }

    const { min, max } = filter;
    if (column.format === "datetime") {
      checks.push((row) => {
        const value = Date.parse(row.cells[index]?.text ?? "");
        if (!Number.isFinite(value)) return false;
        return (min == null || value >= min) && (max == null || value <= max);
      });
      continue;
    }
    checks.push((row) => {
      const value = row.cells[index]?.number;
      // Строка без числа под условие «маржа выше двадцати» не подходит:
      // неизвестная маржа — не то же самое, что подходящая.
      if (value == null) return false;
      return (min == null || value >= min) && (max == null || value <= max);
    });
  }

  return checks.length ? rows.filter((row) => checks.every((check) => check(row))) : rows;
}

// --- состояние в адресе ----------------------------------------------------
//
// Отбор живёт в ссылке, а не в памяти вкладки: «посмотри вот эти четыре»
// пересылают коллеге, и он должен открыть тот же список.
//
// `v.<колонка>` — значения через `|`, `r.<колонка>` — диапазон через `..`.
// Ключ колонки латиницей, поэтому ссылка остаётся читаемой.

const VALUES = "v.";
const RANGE = "r.";

export function readFilters(params: URLSearchParams): FilterState {
  const state: FilterState = new Map();
  params.forEach((raw, name) => {
    if (name.startsWith(VALUES)) {
      const values = raw.split("|").filter(Boolean);
      if (values.length) {
        state.set(name.slice(VALUES.length), { kind: "values", values: new Set(values) });
      }
    } else if (name.startsWith(RANGE)) {
      const [from, to] = raw.split("..");
      const min = from ? Number(from) : null;
      const max = to ? Number(to) : null;
      if (min != null || max != null) {
        state.set(name.slice(RANGE.length), {
          kind: "range",
          min: Number.isFinite(min as number) ? min : null,
          max: Number.isFinite(max as number) ? max : null,
        });
      }
    }
  });
  return state;
}

/** Что записать в адрес, чтобы получился этот отбор. `null` — убрать. */
export function writeFilter(key: string, filter: ColumnFilter | null): Record<string, string | null> {
  const patch: Record<string, string | null> = {
    [`${VALUES}${key}`]: null,
    [`${RANGE}${key}`]: null,
  };
  if (filter === null) return patch;
  if (filter.kind === "values") {
    if (filter.values.size) patch[`${VALUES}${key}`] = [...filter.values].join("|");
  } else if (filter.min != null || filter.max != null) {
    patch[`${RANGE}${key}`] = `${filter.min ?? ""}..${filter.max ?? ""}`;
  }
  return patch;
}

export function clearAll(state: FilterState): Record<string, string | null> {
  const patch: Record<string, string | null> = {};
  for (const key of state.keys()) Object.assign(patch, writeFilter(key, null));
  return patch;
}
