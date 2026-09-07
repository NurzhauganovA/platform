/**
 * Настройка обхода портала: список кодов ЕНС ТРУ.
 *
 * Список задаёт, что вообще попадёт в отбор. На портале сотни тысяч лотов, и
 * обход идёт строго по нему: пустой список означает пустой раздел, а лишний
 * код — сотни чужих строк и запросы к порталу за ними.
 */

import { api } from "@/api/client";

export type WatchedCode = {
  code: string;
  name: string;
  /** Выключенные остаются в списке: по ним видно, что раздел молчит не
   *  потому, что закупок нет, а потому что код убрали. */
  active: boolean;
  note: string;
  /** Наша категория товара. По ней делят работу между людьми. */
  category: string;
  /** Площадка единого портала: ЭГЗ, Mitwork, SKK. Пусто — искать на всех. */
  platform: string;
};

/** Сколько записей уйдёт при очистке раздела. */
export type Purge = {
  lots: number;
  cards: number;
  remarks: number;
  messages: number;
  codes: number;
  total: number;
};

/** Что дала выборка по номеру. Приходит в итоге прогона. */
export type Fetched = {
  number: string;
  /** Чем нашли: по номеру лота или по номеру объявления. Пусто — не нашли. */
  by?: "lot" | "announce" | "";
  found: number;
  added?: number;
  updated?: number;
  /** Сколько карточек завелось. */
  taken: number;
  /** Коды заведённых лотов — по ним человек их и найдёт в списке. */
  codes: string[];
};

export const goszakup = {
  /**
   * Забрать закупку по номеру, мимо списка кодов ЕНС ТРУ.
   *
   * Задачей, а не запросом: портал отвечает секунду в тихий час и полторы
   * минуты в неудачный.
   */
  fetch: (number: string) =>
    api.post<{ job_id: string }>("/api/goszakup/fetch", { number }),

  /** Что удалится — спрашивается до нажатия, а не после. */
  purgePreview: () => api.get<Purge>("/api/goszakup/purge"),

  /** Стирает лоты площадки и всё, что к ним приросло. Отменить нельзя. */
  purge: () => api.delete<Purge>("/api/goszakup/lots"),

  codes: () => api.get<WatchedCode[]>("/api/goszakup/codes"),

  add: (code: string, category = "", note = "", platform = "") =>
    api.post<WatchedCode>("/api/goszakup/codes", {
      code,
      category,
      note,
      platform,
    }),

  setCategory: (code: string, category: string) =>
    api.put<WatchedCode>(
      `/api/goszakup/codes/${encodeURIComponent(code)}/category`,
      { category },
    ),

  setPlatform: (code: string, platform: string) =>
    api.put<WatchedCode>(
      `/api/goszakup/codes/${encodeURIComponent(code)}/platform`,
      { platform },
    ),

  /** Вернуть выключенный код в обход. */
  revive: (code: string) =>
    api.put<WatchedCode>(
      `/api/goszakup/codes/${encodeURIComponent(code)}/active`,
      {},
    ),

  drop: (code: string) =>
    api.delete<void>(`/api/goszakup/codes/${encodeURIComponent(code)}`),
};
