/**
 * Правая колонка карточки: ход лота рельсой.
 *
 * Рельсой, а не стопкой карточек. Шагов у лота семь, и семь одинаковых рамок
 * подряд — список, по которому не видно хода: где были, где стоим, куда
 * дальше. Линия с отметками отвечает на это одним взглядом, а колонка
 * становится короче на треть: отделы свёрнуты, пока их не открыли.
 *
 * Порядок узлов — порядок работы: обсуждение пишется до разбора, разбор до
 * подачи, юрист и снабжение работают между ними. Столбец читают сверху вниз,
 * и порядок узлов это и есть порядок дела.
 *
 * Задача открывается на месте панели, а не окном. Окно закрывает собой лот,
 * ради которого задачу и читают: в ней написано «проверить пункты 4.1–4.6», а
 * пункты — на экране слева.
 *
 * Задачи берутся одним запросом на все узлы. Запрос на отдел — это шесть
 * обращений на открытие карточки ради шести чисел.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { auth } from "@/api/tender";
import {
  cardsApi,
  FLOW,
  type Card,
  type Department,
  type Job,
  type Person,
} from "@/api/cards";
import { ApiError } from "@/api/client";
import { Card as Panel, cx } from "@/ui";
import { NewTask } from "./NewTask";
import { Node, TaskCard, TaskLine } from "./StepRail";
import type { Mark } from "./StepRail";
import { Avatar, Chip, Clock, heat, shortName, stamp } from "./kit";

/** Каким по счёту идёт разбор. По нему видно, пройден он или нет. */
const ANALYSIS_STEP = FLOW.findIndex((step) => step.key === "analysis") + 1;

/**
 * Узлы между разбором и подачей: имя и чей он. Порядок — порядок работы.
 *
 * Перечислены все отделы, а не три ходовых. Задача попадает в отдел и без
 * выбора человека — по статусу лота (`DEPARTMENT_OF` на сервере), — и отдел
 * без узла в рельсе превращал такую задачу в невидимую: свод сверху считал
 * «5 открыто», а по узлам их набиралось два. Числу, которое не сходится с тем,
 * что под ним, перестают верить целиком.
 */
const DESKS: { desk: Department; title: string }[] = [
  { desk: "legal", title: "Юрист" },
  { desk: "supply", title: "Снабжение" },
  { desk: "technologist", title: "Технолог" },
  { desk: "assembler", title: "Сборщик" },
  { desk: "approval", title: "Согласование" },
];

export function Steps({ card, people }: { card: Card; people: Person[] }) {
  const cache = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [openTask, setOpenTask] = useState<string | null>(null);
  const [openNodes, setOpenNodes] = useState<Record<string, boolean>>({});
  const [trouble, setTrouble] = useState("");

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });

  // Все состояния разом: узел показывает «1 из 2» и кто закрыл, а по одним
  // открытым ни того, ни другого не собрать.
  const { data } = useQuery({
    queryKey: ["card-tasks", card.id, "all"],
    queryFn: () => cardsApi.tasks({ card_id: card.id, state: "all" }),
    staleTime: 15_000,
  });
  const tasks = data ?? [];

  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["card-tasks", card.id] });
    void cache.invalidateQueries({ queryKey: ["card-tasks", "open"] });
  };

  const take = useMutation({
    mutationFn: (id: string) => cardsApi.takeTask(id),
    onSuccess: () => {
      setTrouble("");
      refresh();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const release = useMutation({
    mutationFn: (id: string) => cardsApi.releaseTask(id),
    onSuccess: () => {
      setTrouble("");
      refresh();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const finish = useMutation({
    mutationFn: (input: { id: string; result: string }) =>
      cardsApi.closeTask(input.id, "done", input.result),
    onSuccess: () => {
      setTrouble("");
      setOpenTask(null);
      refresh();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const chosen = tasks.find((task) => task.id === openTask);
  if (chosen) {
    return (
      <div className="space-y-2">
        <TaskCard
          task={chosen}
          me={me?.id ?? ""}
          deskName={chosen.department_name}
          busy={take.isPending || finish.isPending || release.isPending}
          onBack={() => setOpenTask(null)}
          onTake={() => take.mutate(chosen.id)}
          onRelease={() => release.mutate(chosen.id)}
          onClose={(result) => finish.mutate({ id: chosen.id, result })}
        />
        {trouble && <p className="text-sm text-critical">{trouble}</p>}
      </div>
    );
  }

  const live = tasks.filter((task) => task.state === "open");
  const closed = tasks.filter((task) => task.state === "done");
  const toggle = (key: string) =>
    setOpenNodes((was) => ({ ...was, [key]: !was[key] }));

  const mayAdd = card.can.includes("task");
  const talk = card.discussion;
  const writing =
    talk?.writing === "queued" || talk?.writing === "running";
  const analysisDone = card.step > ANALYSIS_STEP;
  const signed = card.approvals.filter(
    (one) => one.state === "approved",
  ).length;

  return (
    <>
      <div className="space-y-2">
        {/* Свод и кнопка одной строкой. Кнопка узкая и не переносится: в
            колонке шириной в триста точек обычная разъезжается на две строки и
            уводит свод наверх. */}
        <div className="flex items-center justify-between gap-2 px-1">
          <span className="min-w-0 truncate text-[12.5px] text-ink-secondary tabular-nums">
            Задачи: <b className="font-semibold text-ink">{live.length}</b>{" "}
            открыто · {closed.length} закрыто
          </span>
          {mayAdd && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className={cx(
              "h-7 shrink-0 rounded-[7px] border border-baseline bg-surface px-2.5",
              "text-[12.5px] font-medium whitespace-nowrap text-ink transition hover:bg-plane",
              "focus-visible:outline focus-visible:outline-2",
              "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
            )}
          >
            Новая задача
          </button>
          )}
        </div>

        <Panel className="px-0 py-0.5">
          {/* Обсуждение: срок свой, два рабочих дня со дня публикации. */}
          <Rung
            first
            title="Обсуждение"
            desk="discussion"
            tasks={tasks}
            open={openNodes.discussion}
            onToggle={() => toggle("discussion")}
            onOpenTask={setOpenTask}
            mark={
              writing
                ? "active"
                : !talk
                ? "idle"
                : talk.stage === "sent"
                  ? "done"
                  : talk.overdue || talk.burning
                    ? "hot"
                    : "active"
            }
            right={
              // Пока модель пишет, срок неважен: вопрос к узлу в этот момент
              // один — идёт ли работа. Обсуждение заводится и пишется само,
              // когда лот берут в работу, и без этой пометки пустой текст
              // выглядит как незаведённое обсуждение.
              writing ? (
                <Chip tone="blue">модель пишет</Chip>
              ) : talk ? (
                talk.stage === "sent" ? (
                  <Chip tone="ok">Отправлено</Chip>
                ) : talk.deadline ? (
                  <Clock due={talk.deadline} />
                ) : null
              ) : (
                <span className="text-[11.5px] text-ink-muted">
                  не заводили
                </span>
              )
            }
            meta={
              talk ? (
                <Link
                  to={`/goszakup/remarks/${talk.id}`}
                  className="text-series-1 hover:underline"
                >
                  {talk.stage_name} →
                </Link>
              ) : null
            }
          />

          {/* Разбор: своего срока нет, идёт по сроку подачи. */}
          <Rung
            title="Разбор"
            desk="analysis"
            tasks={tasks}
            open={openNodes.analysis}
            onToggle={() => toggle("analysis")}
            onOpenTask={setOpenTask}
            mark={analysisDone ? "done" : card.burning ? "hot" : "active"}
            right={card.deadline ? <Clock due={card.deadline} /> : null}
            meta={
              card.owner ? (
                <span className="inline-flex items-center gap-1.5">
                  <Avatar name={card.owner} />
                  Ведёт {shortName(card.owner)}
                </span>
              ) : (
                <span className="text-ink-muted">ничей</span>
              )
            }
          />

          {DESKS.map(({ desk, title }) => (
            <Rung
              key={desk}
              title={title}
              desk={desk}
              tasks={tasks}
              open={openNodes[desk]}
              onToggle={() => toggle(desk)}
              onOpenTask={setOpenTask}
            />
          ))}

          {/* Подача: свои задачи и пять подписей чёрточками. Число рядом —
              цвет сам по себе не говорит, сколько собрано. */}
          <Rung
            last
            title="Подача"
            desk="submission"
            tasks={tasks}
            open={openNodes.submission}
            onToggle={() => toggle("submission")}
            onOpenTask={setOpenTask}
            // Собранные подписи важнее сроков задач: без них статус недоступен,
            // и узел «сделан» именно по ним.
            mark={card.approved ? "done" : undefined}
            right={
              card.approve_by ? (
                <span className="text-[11.5px] whitespace-nowrap text-ink-muted tabular-nums">
                  подписи до {stamp(card.approve_by)}
                </span>
              ) : undefined
            }
            meta={
              <span className="flex items-center gap-2">
                <span className="inline-flex gap-[3px]">
                  {card.approvals.map((one) => (
                    <i
                      key={one.kind}
                      title={`${one.name}: ${one.state === "approved" ? "согласовал" : one.state === "rejected" ? "отклонил" : "ждём"}`}
                      className={cx(
                        "block h-[4px] w-[14px] rounded-sm",
                        one.state === "approved"
                          ? "bg-good"
                          : one.state === "rejected"
                            ? "bg-critical"
                            : "bg-baseline",
                      )}
                    />
                  ))}
                </span>
                <span className="tabular-nums">
                  {signed} из {card.approvals.length || 5}
                </span>
              </span>
            }
          />
        </Panel>

        {trouble && <p className="px-1 text-sm text-critical">{trouble}</p>}
      </div>

      {adding && (
        <NewTask
          card={card}
          people={people}
          onClose={() => setAdding(false)}
        />
      )}
    </>
  );
}

/**
 * Узел отдела: свод по его задачам.
 *
 * Ближайший срок из открытых — тот, что горит первым. Остальные видно в
 * развёрнутом списке; выносить наверх все значило бы столбец из десяти чисел,
 * по которому не понять, за что браться.
 */
function Rung({
  title,
  desk,
  tasks,
  open,
  onToggle,
  onOpenTask,
  mark,
  right,
  meta,
  first,
  last,
}: {
  title: string;
  desk: Department;
  tasks: Job[];
  open?: boolean;
  onToggle: () => void;
  onOpenTask: (id: string) => void;
  /** Отметка задана снаружи — у этапов она про лот, а не про задачи. */
  mark?: Mark;
  right?: React.ReactNode;
  meta?: React.ReactNode;
  first?: boolean;
  last?: boolean;
}) {
  // Отменённые не в счёт: их не делали, и «1 из 2» с отменённой во второй
  // означало бы, что половина работы не сделана, хотя работа была одна.
  const mine = tasks.filter(
    (task) => task.department === desk && task.state !== "cancelled",
  );
  const live = mine
    .filter((task) => task.state === "open")
    .sort((a, b) => (a.due_at || "9").localeCompare(b.due_at || "9"));
  const done = mine
    .filter((task) => task.state === "done")
    .sort((a, b) => (b.done_at || "").localeCompare(a.done_at || ""));

  const near = live[0];
  const own: Mark =
    mark ??
    (live.length
      ? heat(near?.due_at) === "hot"
        ? "hot"
        : "active"
      : mine.length
        ? "done"
        : "idle");

  return (
    <Node
      first={first}
      last={last}
      mark={own}
      title={title}
      open={open}
      onToggle={onToggle}
      right={
        right ??
        (near?.due_at ? (
          <Clock due={near.due_at} />
        ) : (
          <span className="text-[11.5px] text-ink-muted">
            {mine.length ? "все задачи закрыты" : "задач нет"}
          </span>
        ))
      }
      meta={meta}
      counts={
        mine.length > 0 ? (
          /* Долей, а не двумя числами со словами. «1 открыто · 1 закрыто»
             человек складывает в уме, чтобы понять, сколько работы всего, —
             а спрашивает он именно это: «2/3» читается сразу и не требует
             арифметики. Что означают числа, сказано словами в своде наверху
             колонки. */
          <span className="flex flex-wrap items-center gap-x-2">
            <span title={`${done.length} из ${mine.length} задач закрыто`}>
              <b className="font-semibold text-ink">{done.length}</b>/
              {mine.length}
            </span>
            {live.some((task) => !task.taken_at) && (
              <Chip tone="blue">есть свободная</Chip>
            )}
          </span>
        ) : null
      }
    >
      {/* Открытые и закрытые подряд, одним списком. Складка «показать
          закрытые» прятала половину ответа на вопрос «что тут делали»: узел
          раскрывают именно ради него, и второе нажатие ради второй половины
          — это нажатие, которое делают всегда. */}
      {mine.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          {[...live, ...done].map((task) => (
            <TaskLine
              key={task.id}
              task={task}
              onOpen={() => onOpenTask(task.id)}
            />
          ))}
        </div>
      )}
    </Node>
  );
}
