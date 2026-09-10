/**
 * Лоты в работе: карточка, задачи, согласование.
 *
 * Что можно сделать с лотом, решает сервер и присылает списком в `can`.
 * Держать эти правила ещё и здесь значит завести второй набор: путь длинный,
 * ветвится в четырёх местах, и разойдутся они на том шаге, который необратим.
 */

import { api } from "@/api/client";

/** Где лот в сквозном процессе. Порядок объявления — порядок жизни. */
export type LotStatus =
  | "new"
  | "discussion"
  | "analysis"
  | "approval"
  | "ready"
  | "awaiting"
  | "won"
  | "lost"
  | "contract"
  | "fulfilling"
  | "awaiting_payment"
  | "done"
  | "skipped"
  | "cancelled";

export type Participation = "maybe" | "yes" | "no";

export type Department =
  | "discussion"
  | "analysis"
  | "supply"
  | "legal"
  | "technologist"
  | "assembler"
  | "approval"
  | "submission";

export type ApprovalKind =
  "manager" | "supply" | "legal" | "technologist" | "assembler";

export type ApprovalState = "waiting" | "approved" | "rejected";

export type TaskState = "open" | "done" | "cancelled";

export type Sign = {
  kind: ApprovalKind;
  name: string;
  state: ApprovalState;
  by: string;
  at: string;
  note: string;
  /** Может ли этот человек поставить именно эту подпись. */
  can_sign: boolean;
};

export type Card = {
  id: string;
  module: string;
  row_id: string;
  code: string;
  /** Номер закупки на площадке. По нему открывают разбор и ищут на портале. */
  source_number: string;
  title: string;
  customer: string;
  amount: number | null;
  enstru_code: string;
  category: string;

  status: LotStatus;
  status_name: string;
  /** Какой это шаг пути, считая с единицы. Ноль — лот сошёл с дистанции. */
  step: number;
  participation: Participation;
  skip_reason: string;

  manager: string;
  manager_id: string;
  owner: string;
  owner_id: string;

  deadline: string;
  left: string;
  burning: boolean;
  overdue: boolean;

  /** До какого момента нужно собрать подписи. Срок приёма минус два часа. */
  approve_by: string;
  approve_left: string;
  approve_burning: boolean;
  approve_overdue: boolean;

  note: string;
  won_amount: number | null;
  winner: string;
  /** Когда лот взяли в работу. Первый вопрос к залежавшейся карточке. */
  started_at: string;
  submitted_at: string;
  finished_at: string;

  approvals: Sign[];
  approved: boolean;
  open_tasks: number;
  done_tasks: number;
  can: string[];
  /** Обсуждение по лоту. Пусто — его не заводили. В списке карточек не
   *  приходит: там оно не показывается, а сотня чтений ради него лишняя. */
  discussion: Talk | null;
};

/** Этап обсуждения. Наш ход, а не ответ заказчика. */
export type DiscussionStage =
  "drafting" | "moderation" | "lawyers" | "sent" | "not_needed";

/** Обсуждение по лоту коротко — то, что показывает правый столбец. */
export type Talk = {
  id: string;
  stage: DiscussionStage;
  stage_name: string;
  /** Срок расчётный: портал своих полей обсуждения не отдаёт. */
  deadline: string;
  left: string;
  burning: boolean;
  overdue: boolean;
  /** Как идёт написание моделью. Пусто — не запускалось. */
  writing: "" | "queued" | "running" | "ready" | "failed";
};

export type Job = {
  id: string;
  card_id: string;
  card_code: string;
  card_title: string;
  department: Department;
  department_name: string;
  title: string;
  body: string;
  assignee: string;
  assignee_id: string;
  due_at: string;
  left: string;
  burning: boolean;
  overdue: boolean;
  state: TaskState;
  result: string;
  created_at: string;
  /** Когда взяли. Пусто — задача ещё ничья: срок при этом тот же, его назначил
   *  автор, — просто делать её пока некому. */
  taken_at: string;
  done_at: string;
  /** Кто закрыл. Не тот же, кто взял: задачу передают и доделывают за коллегу. */
  done_by: string;
  /** Кто поставил. Вопрос «а кто это придумал» адресуют не исполнителю. */
  author: string;
};

export type Person = { id: string; name: string; role: string };

/** Одно действие над лотом. По ленте считают, кому платить премию. */
export type LotEvent = {
  id: string;
  at: string;
  actor: string;
  actor_id: string;
  /** Роль на момент действия, а не сегодняшняя. */
  actor_role: string;
  /** Сделано прогоном или моделью: премию получает человек, не робот. */
  by_machine: boolean;
  kind: string;
  title: string;
  detail: string;
  from_status: string;
  to_status: string;
};

/** Сколько сделал человек по лоту. Считает сервер: по этому делят премию. */
export type Worker = {
  name: string;
  user_id: string;
  role: string;
  actions: number;
  first_at: string;
  last_at: string;
};

/** Сколько лот простоял на этапе и у кого. Отвечает на «где застряло». */
export type Stage = {
  status: LotStatus;
  name: string;
  seconds: number;
  owner: string;
  /** Этап идёт прямо сейчас. */
  running: boolean;
};

export type History = {
  events: LotEvent[];
  workers: Worker[];
  stages: Stage[];
};

export type Attachment = {
  id: string;
  name: string;
  sha256: string;
  size_bytes: number;
  note: string;
  added_by: string;
  added_at: string;
  /** В какой папке лежит. Пусто — в корне. */
  folder_id: string;
};

/**
 * Ответ на загрузку файла.
 *
 * Отличается от строки списка одним полем — рассказом о том, что произошло.
 * Файлы сравниваются по содержимому, а не по имени, и повторная загрузка того
 * же документа в другую папку переносит его, а не заводит вторую запись:
 * человеку про это надо сказать, иначе файл выглядит пропавшим оттуда, где
 * лежал.
 */
export type Uploaded = Attachment & {
  /** Что стоит сказать про эту загрузку. Пусто — говорить нечего. */
  notice: string;
};

/**
 * Папка для файлов лота.
 *
 * Снабжение находит товар в Китае: снимки переписки в WeChat, счета,
 * договоры на китайском. Одним списком это перестаёт быть находимым уже на
 * десятом файле.
 */
export type Folder = {
  id: string;
  name: string;
  /** Сколько файлов внутри. Пустая папка — не ошибка: её завели заранее. */
  files: number;
};

export type CardFilters = {
  module?: string;
  status?: LotStatus;
  participation?: Participation;
  category?: string;
  enstru_code?: string;
  amount_from?: number;
  amount_to?: number;
  mine?: boolean;
  unowned?: boolean;
  burning?: boolean;
  search?: string;
};

function query(filters: Record<string, unknown>): string {
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

export const cardsApi = {
  list: (filters: CardFilters = {}) =>
    api.get<Card[]>(`/api/cards${query(filters)}`),

  one: (id: string) => api.get<Card>(`/api/cards/${id}`),

  history: (id: string) => api.get<History>(`/api/cards/${id}/history`),

  /** Заводит карточку по строке рабочего списка. Повторно — возвращает ту же. */
  open: (body: {
    module: string;
    row_id: string;
    code: string;
    source_number?: string;
    title: string;
    customer?: string;
    amount?: number | null;
    enstru_code?: string;
    category?: string;
    deadline?: string | null;
  }) => api.post<Card>("/api/cards", body),

  move: (id: string, to: LotStatus, reason = "") =>
    api.post<Card>(`/api/cards/${id}/move`, { to, reason }),

  decide: (id: string, participation: Participation, reason = "") =>
    api.post<Card>(`/api/cards/${id}/decide`, { participation, reason }),

  sign: (id: string, kind: ApprovalKind, state: ApprovalState, note = "") =>
    api.post<Card>(`/api/cards/${id}/sign`, { kind, state, note }),

  assign: (
    id: string,
    body: {
      manager_id?: string | null;
      owner_id?: string | null;
      change_manager?: boolean;
      change_owner?: boolean;
    },
  ) => api.post<Card>(`/api/cards/${id}/assign`, body),

  people: () => api.get<Person[]>("/api/cards/people"),

  tasks: (
    filters: {
      department?: Department;
      mine?: boolean;
      unassigned?: boolean;
      card_id?: string;
      /** `all` — и открытые, и закрытые. Умолчание — только открытые. */
      state?: TaskState | "all";
    } = {},
  ) => api.get<Job[]>(`/api/cards/tasks${query(filters)}`),

  addTask: (
    cardId: string,
    body: {
      title: string;
      body?: string;
      department?: Department;
      assignee_id?: string | null;
      due_at?: string | null;
    },
  ) => api.post<Job>(`/api/cards/${cardId}/tasks`, body),

  closeTask: (taskId: string, state: TaskState = "done", result = "") =>
    api.post<Job>(`/api/cards/tasks/${taskId}/close`, { state, result }),

  /**
   * Взять задачу себе. Срока здесь нет: его назначает автор при заведении, и
   * берущий его не двигает — иначе задача «к 16:00», взятая в 15:50, молча
   * превращалась в задачу «до 18:50».
   */
  takeTask: (taskId: string, assignee_id?: string | null) =>
    api.post<Job>(`/api/cards/tasks/${taskId}/take`, { assignee_id }),

  /** Вернуть задачу в очередь отдела. Отдельным признаком, а не пустым
   *  исполнителем: пустой сервер понимал как «себе». */
  releaseTask: (taskId: string) =>
    api.post<Job>(`/api/cards/tasks/${taskId}/take`, { release: true }),

  /** Цена, с которой выиграли, или победитель, если выиграли не мы. */
  result: (cardId: string, won_amount: number | null, winner = "") =>
    api.post<Card>(`/api/cards/${cardId}/result`, { won_amount, winner }),

  files: (cardId: string) =>
    api.get<Attachment[]>(`/api/cards/${cardId}/files`),

  attach: (cardId: string, file: File, folderId = "") => {
    const form = new FormData();
    form.append("file", file);
    // Папка уходит вместе с файлом, а не вторым запросом: пачка снимков
    // переписки кладётся в свою папку, и промежуточное состояние «файл уже
    // в корне, сейчас переложим» человек успевает увидеть.
    if (folderId) form.append("folder_id", folderId);
    return api.upload<Uploaded>(`/api/cards/${cardId}/files`, form);
  },

  folders: (cardId: string) =>
    api.get<Folder[]>(`/api/cards/${cardId}/folders`),

  makeFolder: (cardId: string, name: string) =>
    api.post<Folder>(`/api/cards/${cardId}/folders`, { name }),

  /** Убирает папку. Файлы из неё возвращаются в корень, а не удаляются. */
  dropFolder: (folderId: string) =>
    api.delete<{ вернулось_в_корень: number }>(
      `/api/cards/folders/${folderId}`,
    ),

  /** Перекладывает файл. Пустая папка — в корень. */
  moveFile: (linkId: string, folderId: string) =>
    api.post<Attachment>(`/api/cards/files/${linkId}/folder`, {
      folder_id: folderId,
    }),

  detach: (linkId: string) => api.delete<void>(`/api/cards/files/${linkId}`),

  /** Ссылка на скачивание. Хэш в адресе, а не имя: имена повторяются. */
  fileUrl: (cardId: string, sha256: string) =>
    `/api/cards/${cardId}/files/${sha256}`,
};

/** Шаги пути в том порядке, в каком лот их проходит. */
export const FLOW: { key: LotStatus; title: string; short: string }[] = [
  { key: "new", title: "Новый", short: "Новый" },
  { key: "discussion", title: "Обсуждение", short: "Обсужд." },
  { key: "analysis", title: "На разборе", short: "Разбор" },
  { key: "approval", title: "На согласовании", short: "Соглас." },
  { key: "ready", title: "Готов к участию", short: "Готов" },
  { key: "awaiting", title: "Ожидаем итоги", short: "Итоги" },
  { key: "won", title: "Выиграли", short: "Выигр." },
  { key: "contract", title: "Договор", short: "Договор" },
  { key: "fulfilling", title: "Исполнение", short: "Исполн." },
  { key: "awaiting_payment", title: "Ожидаем оплату", short: "Оплата" },
  { key: "done", title: "Завершён", short: "Готово" },
];

/** Сошёл с дистанции: полоса хода для него не рисуется. */
export const OFF_TRACK: LotStatus[] = ["skipped", "lost", "cancelled"];

// --- разбор спецификации таблицей -----------------------------------------

/** Столбец таблицы разбора. */
export type SheetColumn = {
  key: string;
  title: string;
  /** Ширина в точках. Меняется перетаскиванием края заголовка. */
  width: number;
  /** `model` — заполняет модель и перезаписывает при пересборке;
   *  `hand` — завёл человек, пересборка его не трогает. */
  filled_by: "model" | "hand";
};

export type SheetRow = {
  key: string;
  cells: Record<string, string>;
};

export type Sheet = {
  columns: SheetColumn[];
  rows: SheetRow[];
  /** Какой это вариант разбора: «A», «B», «C»… */
  variant: string;
  /** Какие варианты есть у лота. «A» — всегда. */
  variants: string[];
  /** Что можно сделать с вариантами: `branch`, `drop`. Решает сервер. */
  can: string[];
  /** Файл, по которому собрано. По нему видно, не устарела ли таблица. */
  source_name: string;
  model: string;
  /** Почему не собралось. Пустая таблица без причины читается как поломка. */
  trouble: string;
  built_at: string;
  /** Разбор, который идёт прямо сейчас. Пусто — не идёт.
   *
   *  Приходит с сервера, а не помнится вкладкой: разбор запускается сам при
   *  взятии лота в работу, и открывший карточку позже должен видеть ход
   *  работы, а не пустую таблицу. */
  job_id: string;
};

export const sheetApi = {
  // Вариант — параметром адреса, а не полем тела: по адресу совпадает ключ
  // кэша, и таблица B не подменяет собой таблицу A в памяти вкладки.
  get: (cardId: string, variant = "A") =>
    api.get<Sheet>(`/api/cards/${cardId}/sheet?variant=${variant}`),

  save: (
    cardId: string,
    variant: string,
    body: { columns: SheetColumn[]; rows: SheetRow[] },
  ) => api.put<Sheet>(`/api/cards/${cardId}/sheet?variant=${variant}`, body),

  /** Ставит разбор в очередь: модель стоит денег и думает минуту. */
  build: (cardId: string, variant = "A") =>
    api.post<{ job_id: string }>(
      `/api/cards/${cardId}/sheet?variant=${variant}`,
    ),

  /** Заводит следующий вариант от «A»: требования те же, свои столбцы пустые. */
  branch: (cardId: string) =>
    api.post<Sheet>(`/api/cards/${cardId}/sheet/variants`),

  drop: (cardId: string, variant: string) =>
    api.delete<Sheet>(`/api/cards/${cardId}/sheet/variants/${variant}`),
};
