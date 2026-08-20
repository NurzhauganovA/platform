/**
 * Разрезы рабочего списка: что считается на странице аналитики.
 *
 * Считается из того же ответа, что рисует таблицу. Отдельного запроса нет
 * намеренно: список уже лежит в памяти вкладки после того, как человек
 * посмотрел раздел, и второй раз просить у сервера то же самое — это лишний
 * мегабайт и три секунды на переход между двумя экранами одного раздела.
 *
 * Какая колонка чем является, говорит сервер (`column.role`). Разбирать
 * заголовки здесь нельзя: у трёх разделов они разные, и правило по ним
 * сломается на площадке, которую добавят следующей.
 *
 * Разрез — любая пригодная колонка, а не только «категория». По умолчанию
 * открывается та, что помечена ролью `category`, но заказчик, папка и признак
 * закупки отвечают на не менее частые вопросы: «сколько мы возим Акбастау» и
 * «где деньги — в товарах или в услугах».
 */

import type { Worklist, WorklistColumn, WorklistRow } from "@/api/worklist";

export interface Slice {
  /** Значение разреза: название категории, имя заказчика. */
  name: string;
  rows: number;
  /** Сумма закупок. `null` — раздел не знает цены всей закупки. */
  total: number | null;
  cost: number | null;
  profit: number | null;
  /** Медиана маржи. Среднее здесь врёт: одна находка не того товара даёт
   *  тысячу процентов и утаскивает весь разрез. */
  margin: number | null;
  /** Сколько строк с зелёным решением — доля работы, за которую стоит браться. */
  good: number;
  /** По скольким себестоимость известна: остальное не «невыгодно», а «не с чем
   *  сравнивать», и смешивать их нельзя. */
  priced: number;
}

export function indexOfRole(columns: WorklistColumn[], role: string): number {
  return columns.findIndex((column) => column.role === role);
}

/** Роли, которые модуль объявил разрезами: их показываем всегда. */
const CUTS = new Set(["category", "customer"]);

/**
 * Колонки, по которым имеет смысл резать.
 *
 * Объявленная роль перебивает любые пороги: если модуль сказал, что это
 * заказчик, значит по нему режут — даже когда заказчиков восемьдесят на сто
 * строк. Пороги нужны для остальных колонок, где приходится догадываться по
 * данным: уникальное в каждой строке — не разрез, а список, и «Название
 * закупки» дало бы триста столбиков по одному.
 */
export function sliceable(data: Worklist): WorklistColumn[] {
  const rows = data.rows.length;
  if (!rows) return [];
  return data.columns.filter((column, index) => {
    if (column.compact || column.format !== "text") return false;
    const distinct = new Set(data.rows.map((row) => row.cells[index]?.text?.trim() ?? "")).size;
    if (distinct < 2) return false;
    if (CUTS.has(column.role)) return true;
    return distinct <= 60 && distinct <= rows * 0.6;
  });
}

/**
 * Какой разрез открыть первым.
 *
 * Сначала категория — вопрос «в чём мы сильны» задают чаще прочих, потом
 * заказчик. Обе роли объявляет модуль. Если ни одной нет, берётся первая
 * пригодная колонка: разрез по решению повторяет кольцо рядом, но это лучше,
 * чем пустая страница.
 */
export function defaultSlice(data: Worklist): string {
  for (const role of ["category", "customer"]) {
    const found = data.columns.find((column) => column.role === role);
    if (found) return found.key;
  }
  return sliceable(data)[0]?.key ?? "";
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = sorted.length / 2;
  return sorted.length % 2
    ? sorted[Math.floor(middle)]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function sum(values: number[]): number | null {
  return values.length ? values.reduce((acc, value) => acc + value, 0) : null;
}

function numbers(rows: WorklistRow[], index: number): number[] {
  if (index < 0) return [];
  const result: number[] = [];
  for (const row of rows) {
    const value = row.cells[index]?.number;
    if (value != null) result.push(value);
  }
  return result;
}

function measure(rows: WorklistRow[], columns: WorklistColumn[]) {
  const totalAt = indexOfRole(columns, "total");
  const costAt = indexOfRole(columns, "cost");
  const profitAt = indexOfRole(columns, "profit");
  const marginAt = indexOfRole(columns, "margin");
  return {
    total: sum(numbers(rows, totalAt)),
    cost: sum(numbers(rows, costAt)),
    // Складываем только заработанное: убыточные закупки мы не берём, и
    // вычитать их значило бы показать несуществующий итог.
    profit: sum(numbers(rows, profitAt).filter((value) => value > 0)),
    margin: median(numbers(rows, marginAt)),
    good: rows.filter((row) => row.tone === "good").length,
    priced: numbers(rows, costAt).length,
  };
}

export function slices(data: Worklist, rows: WorklistRow[], key: string): Slice[] {
  const index = data.columns.findIndex((column) => column.key === key);
  if (index < 0) return [];

  const groups = new Map<string, WorklistRow[]>();
  for (const row of rows) {
    const name = row.cells[index]?.text?.trim() || "— не указано —";
    const bucket = groups.get(name);
    if (bucket) bucket.push(row);
    else groups.set(name, [row]);
  }

  const result: Slice[] = [];
  for (const [name, group] of groups) {
    result.push({ name, rows: group.length, ...measure(group, data.columns) });
  }

  // Сортируем по тому, что раздел вообще знает. У площадок суммы закупки нет
  // — в их книге цена за единицу, — и порядок по ней оставил бы разрезы
  // вперемешку, в порядке появления строк.
  const weight = (item: Slice) => item.total ?? item.profit ?? item.rows;
  return result.sort((left, right) => weight(right) - weight(left) || right.rows - left.rows);
}
