/**
 * Запросы к рабочим спискам — SKStore, OMarket и тендерному отбору.
 *
 * Один слой на все три, потому что и раздела три одинаковых: список закупок
 * с себестоимостью и маржой, разбор строки сбоку, книга Excel. Разводить их
 * по файлам значило бы трижды править одно и то же и однажды забыть третий.
 *
 * С сервера приходит и то, что раньше пришлось бы держать здесь: описание
 * колонок, слова легенды и список доступных кнопок. Это не лень. Колонки
 * задаёт сам проект — те же, что в его книге Excel; слова у разделов разные
 * («участвовать» против «брать»); а кнопка, которую нечем обслужить, хуже
 * отсутствующей. Захардкодь любое из трёх — и оно разойдётся с сервером на
 * разделе, который добавят следующим.
 */

import { api } from "./client";

/** Куда и как выравнивать значение. Формат тот же, что у колонки в книге. */
export type CellFormat = "text" | "money" | "percent" | "quantity" | "datetime";

export interface WorklistColumn {
  key: string;
  title: string;
  /** Ширина из книги Excel, в символах. */
  width: number;
  format: CellFormat;
  align: "left" | "right";
  /** Колонка с деньгами. Приходит только тем, кому положено их видеть. */
  sensitive: boolean;
  /** Показывать значком, а не текстом: целиком содержимое есть в разборе. */
  compact: boolean;
  /** Показывать ли сразу, без прокрутки вбок. */
  essential: boolean;
  /** Что колонка означает по смыслу: `total`, `price`, `cost`, `profit`,
   *  `margin`, `quantity`. Пусто — колонка без особой роли. По ролям
   *  считаются итоги: заголовки у разделов разные, а смысл один. */
  role: string;
}

export interface WorklistCell {
  text: string;
  number: number | null;
  link: string | null;
  /** Отметка на самой ячейке: заливка строки занята вердиктом, а выделить
   *  надо значение — код ЕНС, по которому есть отечественный производитель. */
  tone: Tone;
}

/** Подсветка по вердикту — та же, что заливка строки в книге. */
export type Tone = "" | "good" | "warning" | "info" | "critical";

/** Отметка лота в строке списка. Маржа здесь по всему лоту, а не по строке:
 *  позиция с заработком 40% в лоте, который в минусе, — это ловушка. */
export interface RowLot {
  key: string;
  positions: number;
  total: number | null;
  margin_percent: number | null;
}

export interface WorklistRow {
  cells: WorklistCell[];
  lot: RowLot | null;
  /** Место в списке. Показывать нечего: сдвигается от каждой новой закупки. */
  number: number;
  /** Постоянный код: «TN-00042». Им строку и называют — он выдан один раз и
   *  остаётся при позиции, сколько бы раз список ни пересобирали. */
  code: string;
  /** Чем открыть разбор. Идентификатор площадки, а не номер строки. */
  id: string;
  /** Когда закрывается приём. По нему подсвечивается срочное. */
  deadline: string | null;
  /** Есть ли с этой строкой что делать. Отбор идёт здесь, а не запросом. */
  focus: boolean;
  tone: Tone;
}

// --- разбор одной строки ---------------------------------------------------

export interface DetailField {
  label: string;
  text: string;
  number: number | null;
  format: CellFormat;
  link: string | null;
  tone: "" | "good" | "warning" | "critical";
  /** Оговорка к значению. «Комиссия не известна» важнее самой цифры. */
  note: string;
}

export interface DetailTable {
  columns: string[];
  rows: string[][];
  aligns: string[];
  /** В какой колонке живёт ссылка. */
  link_column: number;
  /** Куда ведёт строка. Находка без ссылки — обещание, а не поставщик. */
  links: string[];
  /** Чем выбрать строку для пересчёта. Пусто — строка не выбирается. */
  picks: string[];
  /** Какие строки сейчас в расчёте: по ним и посчитана себестоимость. */
  chosen: string[];
}

export interface DetailSection {
  title: string;
  fields: DetailField[];
  table: DetailTable | null;
  note: string;
  /** Что сказать, если раздела нет: «конкурентов ещё нет» и «карточку не
   *  читали» — разные ответы, молчание хуже обоих. */
  empty: string;
  /** Показывать свёрнутым. Решает сервер: длина раздела ничего не говорит о
   *  том, насколько он нужен — «как считали себестоимость» короче, но важнее. */
  collapsed: boolean;
}

/** Позиция лота — то, чем переключаются в разборе. */
export interface LotPosition {
  id: string;
  title: string;
  quantity: number | null;
  total: number | null;
  cost: number | null;
  margin_percent: number | null;
  tone: Tone;
  current: boolean;
}

/**
 * Закупка целиком: её позиции и итог по ним.
 *
 * Приходит и до объединения. Сам факт «в этой закупке ещё две позиции» — уже
 * предупреждение: заработок по одной ничего не значит, пока не видно
 * остальных, которые придётся поставить вместе с ней.
 */
export interface Lot {
  key: string;
  merged: boolean;
  positions: LotPosition[];
  total: number | null;
  cost: number | null;
  profit: number | null;
  margin_percent: number | null;
  /** По скольким позициям себестоимость известна. Без этого числа итог врёт
   *  в лучшую сторону: непосчитанная позиция выглядит бесплатной. */
  priced: number;
}

export interface Detail {
  id: string;
  title: string;
  subtitle: string;
  verdict: string;
  tone: Tone;
  /** Ссылка на карточку у площадки — то, ради чего разбор чаще и открывают. */
  url: string | null;
  sections: DetailSection[];
  hidden_sections: number;
  lot: Lot | null;
}

export interface LegendItem {
  /** Пустой тон — тоже запись: «нет данных» надо объяснить так же, как
   *  зелёное. Строка при этом остаётся серой. */
  tone: Tone;
  /** Слово этого раздела: «участвовать», «брать». Из книги того же проекта. */
  title: string;
  hint: string;
}

/** Что можно запустить в разделе. Приходит с сервера: у тендерного отбора нет
 *  ни обновления, ни пересчёта — папки разбирают на машине тендерщика. */
export type WorklistAction = "sync" | "analyze" | "export";

export interface Worklist {
  /** Как этот же список называется в книге: человеку надо знать, с чем сверяться. */
  sheet: string;
  columns: WorklistColumn[];
  rows: WorklistRow[];
  legend: LegendItem[];
  actions: WorklistAction[];
  hidden_columns: number;
  total: number;
  shown: number;
  /** Сколько с истёкшим приёмом. Из базы они не удаляются — это история, —
   *  но в рабочем списке их нет. Видны по кнопке «Все строки». */
  expired: number;
  verdicts: Record<string, number>;
  margin_total: number | null;
  priced: number;
  /** Считали ли вообще. Пустой список без этого признака выглядит как «нечего
   *  смотреть», хотя строки, возможно, просто ещё не оценивали. */
  analyzed: boolean;
}

export interface WorklistHealth {
  ok: boolean;
  core_version: string;
  /** Площадки: настроен ли поиск себестоимости на внешних рынках. */
  market_search?: boolean;
  market_model?: string;
  warehouse?: boolean;
  problems: string[];
  /** SKStore. */
  bargains?: number;
  /** OMarket. */
  preorders?: number;
  /** OMarket: жива ли сессия кабинета. Вход по ЭЦП идёт на машине сотрудника. */
  session?: boolean;
  /** Тендеры: есть ли доступ к модели и заполнены ли реквизиты компаний. */
  model_access?: boolean;
  companies_configured?: number;
}

export type WorklistSlug = "skstore" | "omarket" | "tender";

export type Scope = "focus" | "all";

/**
 * Состав колонок.
 *
 * `key` — то, по чему принимают решение: помещается на экран без прокрутки.
 * `all` — дословно как в книге Excel, все девятнадцать (или семнадцать).
 *
 * Оба состава приходят одним ответом и переключаются на месте: второй запрос
 * ради того, что уже лежит в памяти, — это полсекунды ожидания на каждое
 * нажатие.
 */
export type ColumnSet = "key" | "all";

export const worklists = {
  health: (slug: WorklistSlug) =>
    api.get<WorklistHealth>(`/api/${slug}/health`),

  /**
   * Весь список одним запросом.
   *
   * Отбор строк и колонок делает браузер по признакам в ответе. Так
   * переключатели срабатывают мгновенно, а не ждут полсекунды пересчёта на
   * сервере — при том, что данные уже лежат в памяти вкладки.
   */
  worklist: (slug: WorklistSlug) => api.get<Worklist>(`/api/${slug}/worklist`),

  /**
   * Откуда взялась цифра: решение, деньги, где взять, что проверить.
   *
   * `pick` пересчитывает себестоимость по выбранной находке. Считает сервер:
   * тот же код, которым считается книга, — свой расчёт в браузере разошёлся
   * бы с ней на первой же закупке.
   */
  detail: (slug: WorklistSlug, id: string, pick = "") =>
    api.get<Detail>(
      `/api/${slug}/item/${encodeURIComponent(id)}` +
        (pick ? `?pick=${encodeURIComponent(pick)}` : ""),
    ),

  /**
   * Собрать лот вокруг позиции.
   *
   * Без списка берутся соседи по папке — то, что предложил разбор. Со
   * списком — ровно перечисленные, откуда бы они ни были: заказчик
   * раскладывает один лот по двум папкам, и признака этого в документах нет.
   */
  mergeLot: (slug: WorklistSlug, id: string, positions: string[] = []) =>
    api.post<Lot>(`/api/${slug}/item/${encodeURIComponent(id)}/lot`, {
      positions,
    }),

  /** Разъединить лот целиком или убрать из него одну позицию. */
  splitLot: (slug: WorklistSlug, id: string, only = "") =>
    api.delete<Lot | null>(
      `/api/${slug}/item/${encodeURIComponent(id)}/lot` +
        (only ? `?only=${encodeURIComponent(only)}` : ""),
    ),

  sync: (slug: WorklistSlug) =>
    api.post<{ job_id: string }>(`/api/${slug}/sync`),

  analyze: (slug: WorklistSlug) =>
    api.post<{ job_id: string }>(`/api/${slug}/analyze`),

  /**
   * Остановить прогон. Разбор шестисот закупов с поиском на рынках идёт
   * десятками минут и тратит деньги на каждом — начатый не тем и не вовремя
   * должен прерываться, а не досчитываться.
   */
  cancel: (jobId: string) => api.post<unknown>(`/api/jobs/${jobId}/cancel`),

  /**
   * Книга Excel.
   *
   * Обычной ссылкой, а не через `fetch`: браузер сам покажет диалог
   * сохранения и сам подставит имя файла из заголовка ответа. Скачивание
   * через `fetch` пришлось бы собирать вручную, и имя файла потерялось бы.
   *
   * У тендеров адрес свой: `/api/tender/export` в модуле уже занят выгрузкой
   * нашего КП по одной закупке, а книга отбора — про весь список.
   */
  exportUrl: (slug: WorklistSlug) =>
    slug === "tender" ? "/api/tender/worklist/export" : `/api/${slug}/export`,
};

/** Кусок документа: заголовок, абзац или таблица. */
export interface PreviewBlock {
  kind: "heading" | "text" | "table";
  text: string;
  rows: string[][];
}

/** Лист книги. */
export interface PreviewSheet {
  title: string;
  rows: string[][];
  truncated: boolean;
}

/**
 * Чем показать документ, не выходя из платформы.
 *
 * Приходит разобранным, а не размёткой: собери сервер HTML — и содержимое
 * чужого документа стало бы кодом на нашей странице.
 */
export interface Preview {
  kind: "pdf" | "image" | "document" | "sheet" | "none";
  name: string;
  size_bytes: number;
  blocks: PreviewBlock[];
  sheets: PreviewSheet[];
  truncated: boolean;
  /** Почему показать нельзя. Молчание читается как поломка платформы. */
  note: string;
}

export const files = {
  /** Разбор документа для показа. */
  preview: (slug: WorklistSlug, id: string, sha256: string) =>
    api.get<Preview>(
      `/api/${slug}/item/${encodeURIComponent(id)}/file/${sha256}/view`,
    ),

  /** Сам файл: показывается в окне просмотра и скачивается по кнопке. */
  url: (slug: WorklistSlug, id: string, sha256: string) =>
    `/api/${slug}/item/${encodeURIComponent(id)}/file/${sha256}`,
};
