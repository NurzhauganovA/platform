/**
 * Журнал действий: кто что сделал.
 *
 * Отбор идёт на сервере, а не в браузере. Записей растёт по строке на каждое
 * изменение — за месяц работы отдела это десятки тысяч, и тянуть их в память
 * вкладки ради одного дня означало бы мегабайты по сети на каждое нажатие.
 */

import { api } from "@/api/client";

export interface AuditEntry {
  id: string;
  at: string;
  /** Имя на сегодня. Пусто — действие без входа. */
  who: string;
  who_id: string;
  /** Роль на момент действия, а не сегодняшняя. */
  role: string;
  action: string;
  target: string;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  ip: string;
  /** Что ушло на сервер, без секретов. */
  payload: Record<string, unknown>;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  page: number;
  pages: number;
}

export type AuditQuery = {
  page?: number;
  user_id?: string;
  method?: string;
  since?: string;
  until?: string;
  only_failed?: boolean;
  search?: string;
};

function query(filters: AuditQuery): string {
  const out = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === "" || value === false) continue;
    out.set(key, String(value));
  }
  const tail = out.toString();
  return tail ? `?${tail}` : "";
}

export const audit = {
  list: (filters: AuditQuery = {}) =>
    api.get<AuditPage>(`/api/audit${query(filters)}`),

  people: () => api.get<{ id: string; name: string }[]>("/api/audit/people"),
};
