/**
 * Лоты в работе: карточка, задачи, согласование.
 *
 * Что можно сделать с лотом, решает сервер и присылает списком в `can`.
 * Держать эти правила ещё и здесь значит завести второй набор: путь длинный,
 * ветвится в четырёх местах, и разойдутся они на том шаге, который необратим.
 */

import { api } from "@/api/client";
import type { Message, Preview } from "@/api/worklist";

/** Где лот в сквозном процессе. Порядок объявления — порядок жизни. */
/**
 * Где лот в сквозном процессе. Шесть состояний, а не четырнадцать.
 *
 * Работа отделов — обсуждение, разбор, юрист, технолог, снабжение — идёт
 * внутри «В работе»: они работают параллельно и в любом порядке, а статус,
 * который движется по ним по очереди, врёт ровно в тот момент, когда юрист
 * пишет замечание, а снабжение уже ищет товар.
 */
export type LotStatus = "work" | "approval" | "submission" | "waiting" | "done";

/**
 * Чем кончилась закупка по протоколу итогов.
 *
 * Отдельно от статуса: завершённый лот бывает выигранным, проигранным и
 * никаким. Пустой итог — это «не участвовали», а не «неизвестно»: заявку не
 * подали, протокола по нам нет.
 */
export type LotOutcome = "none" | "won" | "lost";

export type Participation = "maybe" | "yes" | "no";

/** Где обсуждение по лоту — подстатус отбора внутри «В работе». */
export type TalkStage =
  "" | "none" | "running" | "sent" | "accepted" | "rejected" | "not_needed";

/** Одна кнопка второго ряда отбора. */
export type Choice = {
  key: string;
  title: string;
  hint: string;
  /** Какое поле строки сравнивать. Объявляет сервер: вторая такая таблица в
   *  браузере разошлась бы с первой молча. */
  field: "stage" | "talk_stage" | "desk_stage" | "outcome";
  /** `in` — делит свою кнопку; `all` — ищет по всему списку «В работе». */
  scope: "in" | "all";
  /** Из каких подстатусов состоит. Пусто — кнопка сама по себе. */
  of: string[];
  /** Итог, который нельзя поставить молча: нужна причина. */
  needs_reason?: boolean;
  /** Ставится человеком, а не протоколом: заявки по нему не было. */
  by_decision?: boolean;
};

/** Кнопка верхнего ряда со своими подпунктами. */
export type Group = {
  key: string;
  title: string;
  hint: string;
  subs: Choice[];
};

/** Ряды отбора: под «В работе» и под «Завершёнными». */
export type Stages = { work: Group[]; done: Choice[] };

/** Где лот по отделам внутри «В работе». */
export type DeskStage =
  "" | "unowned" | "legal" | "supply" | "done" | "running";

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

/** Строка отдела в карточке: кто им занимается. */
export type Seat = {
  desk: Department;
  title: string;
  name: string;
  user_id: string;
  taken_at: string;
  /** Что можно нажать: `take` — сесть самому, `assign` — посадить другого. */
  can: string[];
};

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
  outcome: LotOutcome;
  outcome_name: string;

  /** Кто взял закупку в работу. Ставится один раз и не переписывается. */
  taken_by: string;
  taken_by_id: string;

  /** Пять отделов и кто в них. */
  seats: Seat[];

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
  /**
   * За сколько подали заявку. Пусто — не подавали.
   *
   * Наша цена участия: не цена закупки (`amount`, объявлена заказчиком) и не
   * цена победителя (`won_amount`). Три разные суммы, и путать их дорого — по
   * первой считают маржу, по третьей понимают, насколько промахнулись.
   */
  bid_amount: number | null;
  won_amount: number | null;
  winner: string;
  /** Когда лот взяли в работу. Первый вопрос к залежавшейся карточке. */
  started_at: string;
  /** Когда статус менялся последний раз. По нему список и отсортирован —
   *  свежее сверху; порядок задаёт сервер, браузер не пересортировывает. */
  status_at: string;
  submitted_at: string;
  /**
   * Подана ли заявка.
   *
   * Шире, чем отметка времени: переводить лот можно откуда угодно куда угодно,
   * и отправленный сразу в «Договор» отметки не получил — а договор без
   * участия не заключают. Считает сервер: второй такой же расчёт здесь
   * разошёлся бы с первым.
   */
  submitted: boolean;
  finished_at: string;

  approvals: Sign[];
  approved: boolean;
  open_tasks: number;
  done_tasks: number;
  can: string[];
  /** Обсуждение по лоту. Пусто — его не заводили. В списке карточек не
   *  приходит: там оно не показывается, а сотня чтений ради него лишняя. */
  discussion: Talk | null;
  /** Ход по отделам: четыре точки в строке списка и галочки в карточке. */
  desks: Desk[];

  /** Где сейчас мяч: лот попадает ровно в одну кнопку верхнего ряда. */
  stage: string;
  stage_name: string;

  /** Где обсуждение по лоту. Считает сервер: исход заказчика в браузер иначе
   *  не приезжает, и «отправлено» от «отклонили» отличить нечем. */
  talk_stage: TalkStage;
  talk_stage_name: string;

  /** Где лот по отделам внутри «В работе». Лестница: лот бывает в двух местах
   *  разом, а строка в списке у него одна. */
  desk_stage: DeskStage;
  desk_stage_name: string;
};

/**
 * Отработал ли отдел по лоту.
 *
 * Считает сервер. Правила у отделов разные — обсуждение закрывается
 * отправкой замечания, разбор переходом этапа, снабжение и технолог
 * закрытыми задачами, — и второй набор этих правил в браузере разошёлся бы с
 * первым на первом же.
 */
export type Desk = {
  desk: string;
  title: string;
  done: boolean;
  /** Сколько задач ещё висит. Ноль при `done: false` — до отдела не дошли. */
  open_tasks: number;
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
  /** Сумма закупки: за что взяться, человек решает по деньгам и сроку. */
  card_amount: number | null;
  /** Заказчик: по нему узнают тех, с кем уже работали. */
  card_customer: string;
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
  /** Кто поставил, ключом: по нему экран решает, показывать ли правку. */
  author_id: string;
  /** Сколько реплик в переписке задачи. Числом на строке: разговор о задаче —
   *  половина работы по ней, и строка без числа выглядит нетронутой. */
  talk: number;
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

  /**
   * Закрывает лот без подачи: не участвуем, отменён, не тот код.
   *
   * Отдельно от «Записать итоги»: тот требует поданной заявки, а здесь её как
   * раз и не было — требовать её значило бы не дать закрыть лот, мимо
   * которого прошли.
   */
  finish: (id: string, outcome: string, reason: string) =>
    api.post<Card>(`/api/cards/${id}/finish`, { outcome, reason }),

  decide: (id: string, participation: Participation, reason = "") =>
    api.post<Card>(`/api/cards/${id}/decide`, { participation, reason }),

  sign: (id: string, kind: ApprovalKind, state: ApprovalState, note = "") =>
    api.post<Card>(`/api/cards/${id}/sign`, { kind, state, note }),

  assign: (
    id: string,
    body: {
      desk: Department;
      user_id?: string | null;
    },
  ) => api.post<Card>(`/api/cards/${id}/assign`, body),

  people: () => api.get<Person[]>("/api/cards/people"),

  /** Из чего собирается второй ряд отбора «В работе». Набор один на
   *  платформу и меняется правкой кода — спрашиваем раз за сессию. */
  stages: () => api.get<Stages>("/api/cards/stages"),

  tasks: (
    filters: {
      department?: Department;
      mine?: boolean;
      unassigned?: boolean;
      /** Задачи одного сотрудника. Пусто и без `mine` — весь отдел. */
      assignee?: string;
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
   * Поручения вне лота: что поручили мне и что поручил я.
   *
   * Отдельно от задач отдела, и это не удвоение: у тех своё право (карточки
   * лотов) и своя очередь, а поручение приходит человеку — технологу,
   * наблюдателю, кому угодно.
   */
  errands: (
    filters: {
      /** both — и мои, и мной поручённые. mine, given, all (администратору). */
      side?: "both" | "mine" | "given" | "all";
      state?: TaskState | "all";
    } = {},
  ) => api.get<Job[]>(`/api/cards/errands${query(filters)}`),

  addErrand: (body: {
    title: string;
    body?: string;
    assignee_id: string;
    due_at?: string | null;
  }) => api.post<Job>("/api/cards/errands", body),

  /** Правка поручения. Смена исполнителя — признаком: «не указан» и «указан
   *  пустым» в JSON приходят одинаково. */
  editErrand: (
    taskId: string,
    body: {
      title?: string;
      body?: string;
      assignee_id?: string | null;
      change_assignee?: boolean;
      due_at?: string | null;
      change_due?: boolean;
    },
  ) => api.patch<Job>(`/api/cards/errands/${taskId}`, body),

  closeErrand: (taskId: string, state: TaskState = "done", result = "") =>
    api.post<Job>(`/api/cards/errands/${taskId}/close`, { state, result }),

  /**
   * Переписка внутри задачи.
   *
   * Отдельно от общей ветки лота: та отвечает на «берём или нет», а здесь
   * вопрос свой — «что именно найти», «подойдёт ли вот этот». В общей ветке
   * он тонет, и через неделю не разобрать, о какой из пяти задач шла речь.
   */
  talk: (taskId: string) =>
    api.get<Message[]>(`/api/cards/tasks/${taskId}/talk`),

  say: (taskId: string, body: string, mentions: string[] = []) =>
    api.post<Message>(`/api/cards/tasks/${taskId}/talk`, { body, mentions }),

  fixSaid: (
    taskId: string,
    messageId: string,
    body: string,
    mentions: string[] = [],
  ) =>
    api.patch<Message>(`/api/cards/tasks/${taskId}/talk/${messageId}`, {
      body,
      mentions,
    }),

  dropSaid: (taskId: string, messageId: string) =>
    api.delete<void>(`/api/cards/tasks/${taskId}/talk/${messageId}`),

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
  /**
   * Берёт ничей лот на себя.
   *
   * Отдельно от «поручить другому»: раздавать работу — право руководящее, а
   * взять свободную себе должен любой, кто её делает. Лот с портала берёт
   * госзакупщик, а разбор считает тендерщик.
   */
  claim: (cardId: string, desk: Department = "analysis") =>
    api.post<Card>(`/api/cards/${cardId}/claim`, { desk }),

  /**
   * Отмечает подачу и запоминает, за сколько подали.
   *
   * Сумма обязательна: подача без неё — это та же отметка «подали», ради
   * замены которой всё и делалось. Спрашивают её ровно тогда, когда пришли
   * итоги, и вспомнить через месяц уже некому.
   */
  submit: (cardId: string, amount: number) =>
    api.post<Card>(`/api/cards/${cardId}/submit`, { amount }),

  result: (
    cardId: string,
    won_amount: number | null,
    winner = "",
    outcome?: LotOutcome,
  ) =>
    api.post<Card>(`/api/cards/${cardId}/result`, {
      won_amount,
      winner,
      outcome,
    }),

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
  /** Ссылка на сам файл. `inline` — показать во вкладке, а не скачать. */
  fileUrl: (cardId: string, sha256: string, inline = false) =>
    `/api/cards/${cardId}/files/${sha256}${inline ? "?inline=1" : ""}`,

  /**
   * Разбор файла для показа: абзацы, таблицы, листы.
   *
   * Тот же разбор и тот же просмотрщик, что у документов закупки. Второй
   * способ показывать `.docx` разошёлся бы с первым на первой же таблице с
   * объединёнными ячейками — а таблицы в спецификациях именно такие.
   */
  filePreview: (cardId: string, sha256: string) =>
    api.get<Preview>(`/api/cards/${cardId}/files/${sha256}/view`),
};

/** Шаги пути в том порядке, в каком лот их проходит. */
export const FLOW: { key: LotStatus; title: string; short: string }[] = [
  { key: "work", title: "В работе", short: "В работе" },
  { key: "approval", title: "На согласовании", short: "Соглас." },
  { key: "submission", title: "Подача", short: "Подача" },
  { key: "waiting", title: "Ожидание протокола итогов", short: "Протокол" },
  { key: "done", title: "Завершённый", short: "Готово" },
];

/**
 * Лот, по которому работа кончилась не участием.
 *
 * Полоса хода для него не рисуется: шагов дальше нет. Отдельного состояния
 * под это больше нет — есть завершённый лот, по которому решили не
 * участвовать либо пришёл протокол.
 */
export function offTrack(card: {
  status: LotStatus;
  outcome: LotOutcome;
  participation: Participation;
}): boolean {
  return (
    card.participation === "no" ||
    (card.status === "done" && card.outcome !== "won")
  );
}

/** Итоги протокола — то, чем закупка кончилась. */
export const OUTCOMES: { key: LotOutcome; title: string }[] = [
  { key: "none", title: "Не участвовали" },
  { key: "won", title: "Выиграли" },
  { key: "lost", title: "Проиграли" },
];

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

/** Чья таблица: разбор или снабжение. */
export type SheetKind = "analysis" | "supply";

export type Sheet = {
  columns: SheetColumn[];
  rows: SheetRow[];
  /** Какой это вариант разбора: «A», «B», «C»… */
  variant: string;
  /** Какие варианты есть у лота. «A» — всегда. */
  variants: string[];
  /** Чья это таблица: разбора или снабжения. */
  kind: SheetKind;
  /** Заведена ли снабжению его таблица. По ней вкладка решает, что показывать. */
  handed: boolean;
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
  // Вариант и вид — параметрами адреса, а не полями тела: по адресу совпадает
  // ключ кэша, и таблица снабжения не подменяет собой разбор в памяти вкладки.
  get: (cardId: string, variant = "A", kind: SheetKind = "analysis") =>
    api.get<Sheet>(
      `/api/cards/${cardId}/sheet?variant=${variant}&kind=${kind}`,
    ),

  save: (
    cardId: string,
    variant: string,
    body: { columns: SheetColumn[]; rows: SheetRow[] },
    kind: SheetKind = "analysis",
  ) =>
    api.put<Sheet>(
      `/api/cards/${cardId}/sheet?variant=${variant}&kind=${kind}`,
      body,
    ),

  /** Ставит разбор в очередь: модель стоит денег и думает минуту. */
  build: (cardId: string, variant = "A") =>
    api.post<{ job_id: string }>(
      `/api/cards/${cardId}/sheet?variant=${variant}`,
    ),

  /** Заводит следующий вариант: требования те же, свои столбцы пустые. */
  branch: (cardId: string, kind: SheetKind = "analysis") =>
    api.post<Sheet>(`/api/cards/${cardId}/sheet/variants?kind=${kind}`),

  drop: (cardId: string, variant: string, kind: SheetKind = "analysis") =>
    api.delete<Sheet>(
      `/api/cards/${cardId}/sheet/variants/${variant}?kind=${kind}`,
    ),

  /**
   * Передаёт разбор снабжению — копией таблицы.
   *
   * Копией, а не той же записью: дальше они расходятся. Снабжение заменяет
   * позицию двумя, когда товара нет, и правит количество под кратность
   * упаковки; правки поверх разбора означали бы, что маржа, показанная на
   * согласовании, задним числом перестала сходиться.
   */
  handover: (cardId: string, variant = "A") =>
    api.post<Sheet>(`/api/cards/${cardId}/sheet/handover?variant=${variant}`),
};
