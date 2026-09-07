/**
 * Обсуждения: замечания к технической спецификации.
 *
 * Что можно сделать с замечанием, решает сервер и присылает списком в `can`.
 * Держать эти правила ещё и здесь значит завести второй набор: однажды кнопка
 * есть, а эндпоинт отвечает отказом — самый обидный вид поломки, потому что
 * человек уверен, что сделал.
 */

import { api } from "@/api/client";

/** Этап работы над замечанием. */
export type Stage =
  "drafting" | "moderation" | "lawyers" | "sent" | "not_needed";

/** Чем кончилось у заказчика. */
export type Outcome =
  "waiting" | "accepted" | "rejected" | "closed" | "complaint";

/** Как идёт написание моделью. */
export type Writing = "queued" | "running" | "ready" | "failed";

export type Remark = {
  id: string;
  module: string;
  row_id: string;
  code: string;
  title: string;
  customer: string;
  /** Плановая сумма заказчика, числом. Копейки тут справочные. */
  amount: number | null;
  enstru_code: string;
  category: string;

  stage: Stage;
  stage_name: string;
  outcome: Outcome;
  outcome_name: string;
  writing: Writing;
  trouble: string;

  deadline: string;
  left: string;
  burning: boolean;
  overdue: boolean;

  assignee: string;
  assignee_id: string;
  text: string;
  ai_text: string;
  ai_model: string;
  answer: string;
  sent_at: string;
  answered_at: string;
  /** Что доступно именно этому человеку: этапы плюс `edit` и `resolve`. */
  can: string[];
};

export type Filters = {
  module?: string;
  stage?: Stage;
  outcome?: Outcome;
  mine?: boolean;
  burning?: boolean;
  assignee_id?: string;
  unowned?: boolean;
  category?: string;
  enstru_code?: string;
  amount_from?: number;
  amount_to?: number;
  /** Корзина срока окончания: сегодня, завтра, позже, без срока. */
  ends?: "today" | "tomorrow" | "later" | "none";
};

function query(filters: Filters): string {
  const parts = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    // Ложные и пустые значения не отправляем: `mine=false` в адресе выглядит
    // осознанным отбором и мешает читать ссылку, которой делятся.
    if (
      value === undefined ||
      value === null ||
      value === "" ||
      value === false
    )
      continue;
    parts.set(key, String(value));
  }
  const text = parts.toString();
  return text ? `?${text}` : "";
}

export const remarks = {
  list: (filters: Filters = {}) =>
    api.get<Remark[]>(`/api/remarks${query(filters)}`),

  one: (id: string) => api.get<Remark>(`/api/remarks/${id}`),

  saveText: (id: string, text: string) =>
    api.put<Remark>(`/api/remarks/${id}/text`, { text }),

  move: (id: string, to: Stage) =>
    api.post<Remark>(`/api/remarks/${id}/move`, { to }),

  resolve: (id: string, outcome: Outcome, answer = "") =>
    api.post<Remark>(`/api/remarks/${id}/resolve`, { outcome, answer }),

  assign: (id: string, assignee_id: string | null) =>
    api.post<Remark>(`/api/remarks/${id}/assign`, { assignee_id }),

  /** Заводит обсуждение по лоту госзакупок и ставит написание в очередь. */
  start: (lotNumber: string) =>
    api.post<{ remark_id: string; job_id: string }>(
      `/api/goszakup/lots/${encodeURIComponent(lotNumber)}/remark`,
    ),

  /**
   * Снять застрявшее написание.
   *
   * Пока задача числится идущей, писать заново нельзя — так одно нажатие не
   * стоит двух вызовов модели. Обратная сторона: сбой модели или выкладка
   * посреди прогона запирают обсуждение, и на экране «модель пишет» до конца
   * дня. Отсюда и кнопка.
   */
  stop: (lotNumber: string) =>
    api.post<{ remark_id: string; job_id: string | null }>(
      `/api/goszakup/lots/${encodeURIComponent(lotNumber)}/remark/stop`,
    ),
};
