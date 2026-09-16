/**
 * Задачи: поручения людям, вне лота.
 *
 * Своим разделом, а не вкладкой на столе отдела. Стол отвечает на «что от
 * моего отдела ждут по закупкам»; здесь другое — «собрать доверенности»,
 * «оформить пропуск на склад», «позвонить в банк про гарантию». Работа
 * человека, а не закупки: положить её в очередь снабжения значит засорить ту
 * очередь, ради которой её и заводили.
 *
 * До сих пор такие поручения жили в мессенджере, то есть нигде: срока у них не
 * было, спросить о них было не с кого, а через неделю никто не помнил, кому
 * что говорили.
 *
 * Две стороны на равных: что поручили мне и что поручил я. Вторая половина не
 * менее важна первой — вопрос «а сделали ли то, что я просил» задают ровно
 * тогда, когда уже поздно.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { auth } from "@/api/tender";
import { cardsApi, type Job, type TaskState } from "@/api/cards";
import { useCan } from "@/shell/can";
import { PageHeader } from "@/shell/AppShell";
import {
  Button,
  Card as Panel,
  EmptyState,
  Page,
  Spinner,
  Tabs,
  cx,
} from "@/ui";
import { stamp } from "@/features/cards/kit";
import { ErrandWindow } from "./ErrandWindow";
import { NewErrand } from "./NewErrand";

type Tab = "mine" | "given" | "closed" | "all";

/** Что показывает вкладка: чью сторону и какие состояния спрашивать. */
const SIDES: Record<
  Tab,
  { side: "mine" | "given" | "both" | "all"; state: TaskState | "all" }
> = {
  mine: { side: "mine", state: "open" },
  given: { side: "given", state: "open" },
  // «Все состояния» и отбор закрытых на месте: отменённое — тоже закрытое, а
  // спросить «сделанные и отменённые» одним запросом нечем, и два запроса ради
  // одной вкладки — это два круга до сервера на её открытие.
  closed: { side: "both", state: "all" },
  all: { side: "all", state: "open" },
};

export function TasksPage() {
  const [tab, setTab] = useState<Tab>("mine");
  const [open, setOpen] = useState<Job | null>(null);
  const [adding, setAdding] = useState(false);
  const cache = useQueryClient();
  const can = useCan();
  const admin = can("admin");

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });

  // Все вкладки читаются сразу: числа стоят на самих вкладках, и отложенный
  // запрос показывал бы ноль у «Я поручил» до тех пор, пока по ней не щёлкнут
  // — то есть ровно тому, кто зашёл проверить, сделали ли просимое.
  const mine = useErrands("mine");
  const given = useErrands("given");
  const closed = useErrands("closed");
  const everything = useErrands("all", admin);

  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["errands"] });
    // Задача могла закрыться — уведомления о ней гаснут, а её число на
    // соседних экранах живёт своей жизнью.
    void cache.invalidateQueries({ queryKey: ["desk-tasks"] });
  };

  const tabs: { key: Tab; title: string }[] = [
    { key: "mine", title: "Мне поручили" },
    { key: "given", title: "Я поручил" },
    { key: "closed", title: "Закрытые" },
    ...(admin ? [{ key: "all" as const, title: "Все" }] : []),
  ];

  const counts: Record<string, number> = {
    mine: mine.data?.length ?? 0,
    given: given.data?.length ?? 0,
    closed: closed.data?.length ?? 0,
    all: everything.data?.length ?? 0,
  };

  const shown =
    (tab === "mine"
      ? mine.data
      : tab === "given"
        ? given.data
        : tab === "closed"
          ? closed.data
          : everything.data) ?? [];

  return (
    <>
      <PageHeader
        title="Задачи"
        subtitle="Поручения вне лота: что на вас и что вы поручили"
        action={
          <Button variant="primary" onClick={() => setAdding(true)}>
            Поручить задачу
          </Button>
        }
      />

      <Page>
        <Tabs tabs={tabs} value={tab} counts={counts} onChange={setTab} />

        {mine.isLoading ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем задачи…" />
          </Panel>
        ) : !shown.length ? (
          <Panel>
            <EmptyState
              title={
                tab === "mine"
                  ? "На вас ничего не поручено"
                  : tab === "given"
                    ? "Вы никому ничего не поручали"
                    : tab === "closed"
                      ? "Закрытых поручений нет"
                      : "Поручений нет"
              }
              description={
                tab === "given"
                  ? "«Поручить задачу» — и у просьбы появится срок и исполнитель."
                  : "Задачи по закупкам лежат на столах отделов и в карточках лотов."
              }
            />
          </Panel>
        ) : (
          <Panel className="overflow-hidden">
            <ul className="divide-y divide-hairline">
              {shown.map((task) => (
                <Row
                  key={task.id}
                  task={task}
                  me={me?.id ?? ""}
                  onOpen={() => setOpen(task)}
                />
              ))}
            </ul>
          </Panel>
        )}
      </Page>

      {open && (
        <ErrandWindow
          task={open}
          me={me?.id ?? ""}
          admin={admin}
          onClose={() => setOpen(null)}
          onChanged={(fresh) => {
            setOpen(fresh);
            refresh();
          }}
          onDone={() => {
            setOpen(null);
            refresh();
          }}
        />
      )}

      {adding && (
        <NewErrand
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            refresh();
          }}
        />
      )}
    </>
  );
}

/** Одна вкладка — один запрос. Ключ по вкладке: списки разные, и общий кэш
 *  показывал бы чужую половину под своим заголовком. */
function useErrands(tab: Tab, enabled = true) {
  const { side, state } = SIDES[tab];
  return useQuery({
    queryKey: ["errands", tab],
    queryFn: () => cardsApi.errands({ side, state }),
    select: (rows: Job[]) =>
      tab === "closed" ? rows.filter((row) => row.state !== "open") : rows,
    enabled,
    refetchInterval: 60_000,
  });
}

/**
 * Строка поручения.
 *
 * Кто и кому — в самой строке. Список смешанный: на вкладке «Все» и на
 * «Закрытых» стоят рядом и мои, и чужие, и без имён не понять, чья это
 * просьба и к кому.
 */
function Row({
  task,
  me,
  onOpen,
}: {
  task: Job;
  me: string;
  onOpen: () => void;
}) {
  const mine = task.assignee_id === me;

  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={cx(
          "flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left",
          "transition hover:bg-plane/60",
          "focus-visible:outline focus-visible:outline-2",
          "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
        )}
      >
        <span className="min-w-0 flex-1">
          <span
            className={cx(
              "block truncate text-sm",
              task.state === "open"
                ? "text-ink"
                : "text-ink-muted line-through",
            )}
          >
            {task.title}
          </span>
          <span className="mt-0.5 block truncate text-xs text-ink-muted">
            {/* «Мне» вместо своего имени: человек и так знает, как его зовут,
                а строка «Иванов → Иванов» читается дольше. */}
            {task.author || "—"} → {mine ? "мне" : task.assignee || "—"}
            {task.body && ` · ${task.body}`}
          </span>
        </span>

        {/* Разговор числом: у задачи, о которой уже переписывались, ответ
            обычно и лежит внутри — без числа её открывают последней. */}
        {task.talk > 0 && (
          <span className="shrink-0 text-xs text-ink-muted tabular-nums">
            {task.talk} реплик
          </span>
        )}

        {task.left && task.state === "open" && (
          <span
            className={cx(
              "shrink-0 text-sm tabular-nums whitespace-nowrap",
              task.overdue || task.burning
                ? "font-semibold text-critical"
                : "text-ink-secondary",
            )}
            title={task.due_at ? `Срок: ${stamp(task.due_at)}` : undefined}
          >
            {task.left}
          </span>
        )}

        {task.state !== "open" && (
          <span className="shrink-0 text-xs text-ink-muted">закрыта</span>
        )}
      </button>
    </li>
  );
}
