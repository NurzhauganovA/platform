/**
 * Итоги по тому, что сейчас на экране.
 *
 * Считаются по отобранным строкам, а не по всему списку, и это главное.
 * Плитка, которая показывает «265 закупок» после того, как человек оставил
 * категорию «Насосы», не отвечает ни на один вопрос — а спрашивают у неё
 * ровно одно: сколько денег в том, что я сейчас вижу.
 *
 * Какая колонка чем является, говорит сервер (`column.role`). Разбирать
 * заголовки здесь нельзя: у трёх разделов они разные — «Маржа ₸»,
 * «Заработок всего, ₸», «заработок», — и правило по ним сломается на
 * площадке, которую добавят следующей.
 */

import type { WorklistColumn, WorklistRow } from "@/api/worklist";

export interface Tile {
  label: string;
  value: string;
  unit?: string;
  hint: string;
  tone?: "good" | "warning" | "critical";
}

/** Числа одной колонки по видимым строкам. */
function numbers(rows: WorklistRow[], index: number): number[] {
  const result: number[] = [];
  for (const row of rows) {
    const value = row.cells[index]?.number;
    if (value != null) result.push(value);
  }
  return result;
}

function indexOfRole(columns: WorklistColumn[], role: string): number {
  return columns.findIndex((column) => column.role === role);
}

const money = (value: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);

const compact = (value: number) => {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)} млрд`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)} млн`;
  if (abs >= 1e3) return `${Math.round(value / 1e3)} тыс.`;
  return money(value);
};

export function summarise({
  rows,
  total,
  columns,
  unit,
  goodLabel,
  urgentDays = 2,
}: {
  /** Только то, что видно после отбора. */
  rows: WorklistRow[];
  /** Сколько было до отбора — чтобы показать «118 из 265». */
  total: number;
  columns: WorklistColumn[];
  unit: string;
  /** Слово раздела для зелёного вердикта: «участвовать», «брать». */
  goodLabel: string;
  urgentDays?: number;
}): Tile[] {
  const tiles: Tile[] = [];
  const shown = rows.length;

  tiles.push({
    label: `Показано ${unit}`,
    value: money(shown),
    hint: shown === total ? "весь список" : `из ${money(total)} — остальное отобрано`,
  });

  // Стоит взяться: считается по цвету, а не по слову. Слова у разделов свои,
  // зелёный везде зелёный.
  const good = rows.filter((row) => row.tone === "good").length;
  tiles.push({
    label: goodLabel || "Стоит взяться",
    value: money(good),
    tone: good ? "good" : undefined,
    hint: shown ? `${Math.round((good / shown) * 100)}% показанного` : "маржа выше порога",
  });

  // Объём: сумма закупок там, где раздел её знает. У площадок в книге цена за
  // единицу, и складывать её по строкам нельзя — такой плитки там не будет.
  const totalIndex = indexOfRole(columns, "total");
  if (totalIndex >= 0) {
    const values = numbers(rows, totalIndex);
    tiles.push({
      label: "Объём закупок",
      value: values.length ? compact(values.reduce((sum, value) => sum + value, 0)) : "—",
      unit: "₸",
      hint: `по ${money(values.length)} из ${money(shown)} строк`,
    });
  }

  const profitIndex = indexOfRole(columns, "profit");
  if (profitIndex >= 0) {
    // Складываем только положительное: убыточные закупки мы просто не берём,
    // и вычитать их значило бы показать несуществующий итог.
    const earned = numbers(rows, profitIndex).filter((value) => value > 0);
    tiles.push({
      label: "Заработаем",
      value: earned.length ? compact(earned.reduce((sum, value) => sum + value, 0)) : "—",
      unit: "₸",
      hint: `на ${money(earned.length)} окупающихся`,
    });
  }

  const marginIndex = indexOfRole(columns, "margin");
  if (marginIndex >= 0) {
    const values = numbers(rows, marginIndex).slice().sort((a, b) => a - b);
    // Медиана, а не среднее: одна закупка с маржой в тысячу процентов —
    // а такие в данных есть, это ненайденный товар — утаскивает среднее
    // туда, где не лежит ни одна строка.
    const middle = values.length
      ? values.length % 2
        ? values[(values.length - 1) / 2]
        : (values[values.length / 2 - 1] + values[values.length / 2]) / 2
      : null;
    tiles.push({
      label: "Маржа посередине",
      value: middle == null ? "—" : `${middle.toFixed(1)}`,
      unit: "%",
      hint: "половина строк выше, половина ниже",
    });
  }

  const costIndex = indexOfRole(columns, "cost");
  if (costIndex >= 0) {
    const unpriced = shown - numbers(rows, costIndex).length;
    tiles.push({
      label: "Не с чем сравнить",
      value: money(unpriced),
      tone: unpriced ? "critical" : undefined,
      hint: unpriced ? "себестоимость не нашлась" : "себестоимость есть по всем",
    });
  }

  // Срочное — только там, где у строк вообще есть срок приёма. У тендерной
  // закупки его в данных нет, и плитка не появится.
  if (rows.some((row) => row.deadline)) {
    const edge = Date.now() + urgentDays * 24 * 3600 * 1000;
    const urgent = rows.filter((row) => {
      const at = row.deadline ? Date.parse(row.deadline) : NaN;
      return Number.isFinite(at) && at <= edge;
    }).length;
    tiles.push({
      label: "Горит",
      value: money(urgent),
      tone: urgent ? "warning" : undefined,
      hint: `приём закрывается в ближайшие ${urgentDays} дня`,
    });
  }

  return tiles;
}
