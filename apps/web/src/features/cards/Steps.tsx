/**
 * Шаги лота в правом столбце: обсуждение, разбор, подача, технолог, сборщик.
 *
 * Раньше здесь стояла одна сводка «Задачи» с числами по трём отделам. На
 * вопрос «сколько висит» она отвечала, а на «успеваем ли» — нет: у каждого
 * шага свой срок, и общий на всех срок приёма заявок их не различает. Окно
 * обсуждения закрывается через два рабочих дня после публикации, когда лот
 * ещё числится на разборе, — и человек, глядя на «осталось 6 дней», узнавал о
 * закрытом окне постфактум.
 *
 * Поэтому шаг, а не отдел: у шага есть свой срок, своё состояние, свой
 * ответственный и свои задачи. Блоки идут по ходу работы — обсуждение до
 * разбора, разбор до подачи: столбец читают сверху вниз, и порядок блоков это
 * и есть порядок работы.
 *
 * Задачи считаются здесь же, из того же ответа, что и раньше: «1/2» — сделано
 * из заведённых. Открытых мало, и отдельный запрос на счётчик ради каждого
 * блока был бы пятью запросами на одно открытие карточки.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { auth } from "@/api/tender";
import {
  cardsApi,
  FLOW,
  type ApprovalKind,
  type Card,
  type Department,
  type Job,
  type Person,
} from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, Card as Panel, cx } from "@/ui";
import { Window } from "./Queue";

/** Каким по счёту шагом идёт разбор. По нему видно, пройден он или нет. */
const ANALYSIS_STEP = FLOW.findIndex((step) => step.key === "analysis") + 1;

/** Каким по счёту идёт подача. Раньше него подавать нечего. */
const READY_STEP = FLOW.findIndex((step) => step.key === "ready") + 1;

export function Steps({
  card,
  people,
  onDone,
}: {
  card: Card;
  people: Person[];
  onDone: (fresh: Card) => void;
}) {
  const [open, setOpen] = useState(false);

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });
  const { data } = useQuery({
    queryKey: ["card-tasks", card.id],
    queryFn: () => cardsApi.tasks({ card_id: card.id }),
    staleTime: 15_000,
  });
  const tasks = data ?? [];

  return (
    <>
      <Discussion card={card} tasks={tasks} onOpen={() => setOpen(true)} />
      <Analysis
        card={card}
        tasks={tasks}
        me={me?.id ?? ""}
        onDone={onDone}
        onOpen={() => setOpen(true)}
      />
      <Submission card={card} tasks={tasks} onOpen={() => setOpen(true)} />
      <Signature
        card={card}
        tasks={tasks}
        kind="technologist"
        desk="technologist"
        title="Технолог"
        onOpen={() => setOpen(true)}
      />
      <Signature
        card={card}
        tasks={tasks}
        kind="assembler"
        desk="assembler"
        title="Сборщик"
        onOpen={() => setOpen(true)}
      />

      {open && (
        <Window card={card} people={people} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

/**
 * Обсуждение: срок окна и где замечание.
 *
 * Срок расчётный, и это сказано словом. Портал в открытой части оба своих
 * поля обсуждения отдаёт пустыми, а два рабочих дня со дня публикации — норма
 * закона, а не наше правило; но праздники в расчёт не входят, и человек,
 * который об этом не знает, планировал бы отправку на выходной.
 */
function Discussion({
  card,
  tasks,
  onOpen,
}: {
  card: Card;
  tasks: Job[];
  onOpen: () => void;
}) {
  const talk = card.discussion;

  return (
    <Step
      title="Обсуждение"
      state={talk ? talk.stage_name : "не заводили"}
      dim={!talk}
      when={talk?.deadline ?? ""}
      whenNote="срок расчётный"
      left={talk?.left ?? ""}
      burning={talk?.burning ?? false}
      overdue={talk?.overdue ?? false}
      tasks={count(tasks, "discussion")}
      onTasks={onOpen}
    >
      {talk ? (
        <Link
          to={`/goszakup/remarks/${talk.id}`}
          className="text-sm text-series-1 hover:underline"
        >
          Открыть обсуждение →
        </Link>
      ) : (
        <p className="text-xs text-ink-muted">
          Заводится кнопкой «Обсуждение» в разборе лота.
        </p>
      )}
    </Step>
  );
}

/**
 * Разбор: кто взял лот и что с ним.
 *
 * «Беру на себя» одним нажатием. Список сотрудников для этого же есть ниже, но
 * им назначают другого, а себя ставят по десять раз на дню: выбирать себя из
 * списка в такой момент — три движения вместо одного.
 *
 * Срок пока от подачи заявки: своего у разбора нет, а пустая строка на месте
 * срока читается как «успеваем», хотя ровно этого мы и не знаем.
 */
function Analysis({
  card,
  tasks,
  me,
  onDone,
  onOpen,
}: {
  card: Card;
  tasks: Job[];
  /** Кто смотрит. Себе лот не предлагают взять второй раз. */
  me: string;
  onDone: (fresh: Card) => void;
  onOpen: () => void;
}) {
  const [trouble, setTrouble] = useState("");

  const take = useMutation({
    mutationFn: () =>
      cardsApi.assign(card.id, { owner_id: me, change_owner: true }),
    onSuccess: onDone,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const done = card.step > ANALYSIS_STEP;
  const state =
    card.step === 0
      ? "лот снят"
      : done
        ? "Завершён"
        : card.owner
          ? "В работе"
          : "Никто не взял";

  return (
    <Step
      title="Разбор"
      state={state}
      dim={card.step === 0 || (!done && !card.owner)}
      good={done}
      when={card.deadline}
      whenNote="по сроку подачи"
      left={card.left}
      burning={card.burning}
      overdue={card.overdue}
      tasks={count(tasks, "analysis")}
      onTasks={onOpen}
    >
      <p className="text-sm text-ink-secondary">
        {card.owner ? (
          <>
            Ведёт <span className="font-medium text-ink">{card.owner}</span>
          </>
        ) : (
          "Разбор ничей"
        )}
      </p>
      {me && me !== card.owner_id && card.can.includes("assign") && (
        <Button
          variant="accent"
          onClick={() => take.mutate()}
          disabled={take.isPending}
          title="Поставить себя ответственным за лот"
        >
          {take.isPending ? "Берём…" : "Беру на себя"}
        </Button>
      )}
      {trouble && <p className="text-sm text-critical">{trouble}</p>}
    </Step>
  );
}

/** Подача: срок приёма заявок и подписи, без которых подавать нечем. */
function Submission({
  card,
  tasks,
  onOpen,
}: {
  card: Card;
  tasks: Job[];
  onOpen: () => void;
}) {
  const signed = card.approvals.filter(
    (sign) => sign.state === "approved",
  ).length;
  const state = card.submitted_at
    ? "Подано"
    : card.approved
      ? "Готовы подать"
      : `Подписи ${signed}/${card.approvals.length || 5}`;

  return (
    <Step
      title="Подача"
      state={state}
      good={Boolean(card.submitted_at) || card.approved}
      dim={!card.submitted_at && !card.approved}
      when={card.deadline}
      whenNote={card.step >= READY_STEP ? "" : "приём заявок"}
      left={card.left}
      burning={card.burning}
      overdue={card.overdue}
      tasks={count(tasks, "submission")}
      onTasks={onOpen}
    >
      {/* Согласование собирается раньше подачи: заявку подают руками, и
          подписи, поставленные за десять минут до срока, означают спешку.
          Свой срок отдельной строкой — он на два часа раньше срока приёма. */}
      {!card.approved && card.approve_by && (
        <p className="flex items-baseline gap-2 text-xs">
          <span className="text-ink-muted tabular-nums">
            Подписи до {moment(card.approve_by)}
          </span>
          <span
            className={cx(
              "whitespace-nowrap",
              card.approve_overdue
                ? "text-ink-muted line-through decoration-baseline"
                : card.approve_burning
                  ? "font-semibold text-critical"
                  : "text-ink-muted",
            )}
          >
            {card.approve_overdue ? "срок прошёл" : card.approve_left}
          </span>
        </p>
      )}
    </Step>
  );
}

/** Технолог и сборщик: подпись и своя очередь задач. */
function Signature({
  card,
  tasks,
  kind,
  desk,
  title,
  onOpen,
}: {
  card: Card;
  tasks: Job[];
  kind: ApprovalKind;
  desk: Department;
  title: string;
  onOpen: () => void;
}) {
  const sign = card.approvals.find((item) => item.kind === kind);
  const state =
    sign?.state === "approved"
      ? "Согласовал"
      : sign?.state === "rejected"
        ? "Отклонил"
        : "Ждём подписи";

  return (
    <Step
      title={title}
      state={state}
      good={sign?.state === "approved"}
      bad={sign?.state === "rejected"}
      dim={!sign || sign.state === "waiting"}
      tasks={count(tasks, desk)}
      onTasks={onOpen}
    >
      {sign?.by && (
        <p className="text-xs text-ink-muted">
          {sign.by}
          {sign.at && ` · ${moment(sign.at)}`}
        </p>
      )}
      {/* Причина отказа рядом с отказом: без неё «отклонил» — это вопрос,
          на который идут спрашивать в мессенджер. */}
      {sign?.state === "rejected" && sign.note && (
        <p className="text-sm text-ink-secondary">{sign.note}</p>
      )}
    </Step>
  );
}

/**
 * Один блок шага.
 *
 * Состояние словом, а не только цветом: «согласовал» и «отклонил» при
 * дальтонизме одинаково серые, и подпись под лотом на четыре миллиона по
 * цвету различать нельзя.
 */
function Step({
  title,
  state,
  good,
  bad,
  dim,
  when,
  whenNote,
  left,
  burning,
  overdue,
  tasks,
  onTasks,
  children,
}: {
  title: string;
  state: string;
  good?: boolean;
  bad?: boolean;
  dim?: boolean;
  when?: string;
  whenNote?: string;
  left?: string;
  burning?: boolean;
  overdue?: boolean;
  tasks: { done: number; total: number };
  onTasks: () => void;
  children?: React.ReactNode;
}) {
  return (
    <Panel>
      <div className="flex items-baseline gap-2 border-b border-hairline px-4 py-2.5">
        <h2 className="flex-1 text-sm font-semibold text-ink">{title}</h2>
        <span
          className={cx(
            "text-xs whitespace-nowrap",
            bad
              ? "font-medium text-critical"
              : good
                ? "font-medium text-good"
                : dim
                  ? "text-ink-muted"
                  : "text-ink-secondary",
          )}
        >
          {state}
        </span>
      </div>

      <div className="space-y-2 px-4 py-2.5">
        {when && (
          <p className="flex items-baseline gap-2">
            <span className="text-sm text-ink tabular-nums">
              до {moment(when)}
            </span>
            <span
              className={cx(
                "text-xs whitespace-nowrap",
                overdue
                  ? "text-ink-muted line-through decoration-baseline"
                  : burning
                    ? "font-semibold text-critical"
                    : "text-ink-muted",
              )}
            >
              {overdue ? "срок прошёл" : left || ""}
            </span>
          </p>
        )}
        {when && whenNote && (
          <p className="-mt-1.5 text-[11px] text-ink-muted">{whenNote}</p>
        )}

        {children}

        {/* Задачи строкой, а не блоком: «1/2» отвечает на весь вопрос, а
            что именно за задачи — в окне, куда ведёт то же нажатие. */}
        <button
          type="button"
          onClick={onTasks}
          title="Открыть задачи по лоту"
          className={cx(
            "-mx-1 flex w-[calc(100%+0.5rem)] items-baseline gap-2 rounded-[6px] px-1 py-0.5",
            "text-left transition hover:bg-plane",
            "focus-visible:outline focus-visible:outline-2",
            "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
          )}
        >
          <span className="flex-1 text-xs text-ink-muted">Задачи</span>
          <span
            className={cx(
              "text-xs tabular-nums",
              tasks.total === 0
                ? "text-ink-muted"
                : tasks.done === tasks.total
                  ? "text-good"
                  : "font-semibold text-ink",
            )}
          >
            {tasks.total === 0 ? "нет" : `${tasks.done}/${tasks.total}`}
          </span>
        </button>
      </div>
    </Panel>
  );
}

/** Сделано из заведённых по этому отделу. Отменённые не в счёт: их не делали. */
function count(
  tasks: Job[],
  desk: Department,
): { done: number; total: number } {
  const mine = tasks.filter(
    (task) => task.department === desk && task.state !== "cancelled",
  );
  return {
    done: mine.filter((task) => task.state === "done").length,
    total: mine.length,
  };
}

/** Дата и время коротко: год в правом столбце шириной в триста точек лишний. */
function moment(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? "—"
    : at.toLocaleString("ru-KZ", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}
