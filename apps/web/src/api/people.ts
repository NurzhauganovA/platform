/**
 * Сотрудники и роли.
 *
 * Роль — это набор прав, а не имя. Встроенных десять, их права заданы кодом и
 * не правятся; свои заводятся в платформе и выбирают права из того же
 * закрытого списка — выдать право, которого никто не проверяет, нельзя.
 */

import { api } from "@/api/client";

/** Право так, как его видит администратор. */
export type Permission = {
  key: string;
  title: string;
  about: string;
};

export type WorkRole = {
  key: string;
  title: string;
  about: string;
  permissions: string[];
  /** Встроенная: название не меняется и удалить нельзя, а права правятся. */
  built_in: boolean;
  /** Права правили руками: у встроенной есть куда вернуться. */
  changed: boolean;
  /** Сколько человек её носит. По нему видно, что удалять уже поздно. */
  people: number;
};

export type Person = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  role_title: string;
  is_active: boolean;
  last_login_at: string;
  /** Вход заперт после серии промахов. Снимается любой правкой. */
  locked: boolean;
};

export const peopleApi = {
  permissions: () => api.get<Permission[]>("/api/people/permissions"),
  roles: () => api.get<WorkRole[]>("/api/people/roles"),

  addRole: (body: {
    key: string;
    title: string;
    description?: string;
    permissions: string[];
  }) => api.post<WorkRole>("/api/people/roles", body),

  saveRole: (
    key: string,
    body: { title?: string; description?: string; permissions?: string[] },
  ) => api.patch<WorkRole>(`/api/people/roles/${key}`, body),

  /** Убирает роль. Занятую — только с `force`: люди на ней станут наблюдателями. */
  /** Возвращает встроенной роли заводские права. */
  resetRole: (key: string) =>
    api.post<WorkRole>(`/api/people/roles/${key}/reset`),

  dropRole: (key: string, force = false) =>
    api.delete<void>(`/api/people/roles/${key}${force ? "?force=true" : ""}`),

  list: () => api.get<Person[]>("/api/people"),

  add: (body: {
    email: string;
    full_name?: string;
    role: string;
    password: string;
  }) => api.post<Person>("/api/people", body),

  save: (
    id: string,
    body: {
      full_name?: string;
      role?: string;
      is_active?: boolean;
      password?: string;
    },
  ) => api.patch<Person>(`/api/people/${id}`, body),

  /** Выключает вход. Запись остаётся и читается по имени. */
  disable: (id: string) => api.delete<void>(`/api/people/${id}`),

  /**
   * Удаляет запись целиком.
   *
   * Работа переживает удаление: подписи и лента событий держат имя автора
   * копией рядом со ссылкой. Уносит удаление только собственное человека —
   * сессии, коды восстановления и место в организации; лоты, которые он вёл,
   * становятся ничьими.
   */
  purge: (id: string) => api.delete<void>(`/api/people/${id}?purge=true`),
};
