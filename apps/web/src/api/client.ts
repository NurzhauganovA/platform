/**
 * Обращение к API.
 *
 * Один слой на всё приложение, и не ради красоты: здесь решается, что делать
 * с 401. Сессия живёт двенадцать часов и истекает посреди работы — без общей
 * обработки каждая страница ловила бы это по-своему, а человек видел бы
 * пустой экран вместо формы входа.
 *
 * Кука ходит сама: `credentials: "include"`. Токенов в localStorage нет
 * намеренно — то, что доступно скриптам страницы, крадётся любой найденной
 * XSS, а за этой сессией лежат себестоимость и маржа.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Сессия истекла или её нет. */
  get isUnauthorized() {
    return this.status === 401;
  }

  /** Роль не позволяет: не ошибка, а граница доступа. */
  get isForbidden() {
    return this.status === 403;
  }
}

type Options = Omit<RequestInit, "body"> & { body?: unknown };

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, headers, ...rest } = options;

  const isForm = body instanceof FormData;
  const response = await fetch(path, {
    ...rest,
    credentials: "include",
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    body: isForm ? body : body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response), await safeJson(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function readError(response: Response): Promise<string> {
  const data = await safeJson(response);
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // Ошибки проверки приходят списком — показываем первую понятную строку.
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
  }
  return `Ошибка ${response.status}`;
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.clone().json();
  } catch {
    return undefined;
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** Загрузка файла: тело — FormData, заголовок ставит браузер. */
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};
