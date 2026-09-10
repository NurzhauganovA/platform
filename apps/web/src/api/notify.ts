/**
 * Уведомления глазами администратора.
 *
 * Состояние приходит от платформы, а платформа спрашивает его у сервиса
 * уведомлений: реестр людей и привязки — его, человек настраивает их в боте.
 * Свой список в браузере означал бы экран, который показывает привязку,
 * снятую вчера.
 */

import { api } from "@/api/client";

/** Что сейчас с сервисом уведомлений. */
export type NotifyState = {
  /** Задан ли адрес и ключ. Нет — уведомления выключены совсем. */
  configured: boolean;
  url: string;
  /** Дошли ли до него из контейнера платформы, а не с машины. */
  reachable: boolean;
  /** Чем кончилась попытка, если не дошли. */
  trouble: string;
  telegram: boolean;
  email: boolean;
  environment: string;
  /** Пробелы в настройках, которые сервис нашёл у себя сам. */
  problems: string[];
  /** Жива ли его база. Готовность сервиса этого не показывает. */
  database: boolean;

  recipients: number;
  active: number;
  telegram_linked: number;
  pending: number;
  sent_24h: number;
  failed_24h: number;
  skipped_24h: number;

  /** Сколько работающих сотрудников в базе платформы. Рядом с `recipients`
   *  отвечает, доехал ли реестр вообще. */
  people_here: number;
};

export type NotifyPerson = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  /** Знает ли его сервис. Нет — бот не найдёт его почту и код не отправит. */
  known: boolean;
  telegram_linked: boolean;
  telegram_name: string;
  telegram_enabled: boolean;
  email_enabled: boolean;
  /** Человек остановил бота: привязка на месте, а Телеграм молчит. */
  stop_reason: string;
};

export type Delivery = {
  channel: string;
  status: string;
  target: string;
  /** Причина неудачи словами. Она лежит у доставки, а не у уведомления. */
  error: string;
};

export type Sent = {
  at: string;
  event: string;
  title: string;
  deliveries: Delivery[];
};

export const notifyApi = {
  state: () => api.get<NotifyState>("/api/notify"),
  people: () => api.get<NotifyPerson[]>("/api/notify/people"),
  sync: () => api.post<NotifyState>("/api/notify/sync"),
  history: (userId: string) =>
    api.get<Sent[]>(`/api/notify/people/${userId}/history`),
  test: (userId: string) => api.post<Sent>(`/api/notify/people/${userId}/test`),
};
