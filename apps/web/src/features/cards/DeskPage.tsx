/**
 * Стол отдела: задачи и лоты, которые на нём.
 *
 * Один экран на юристов, снабжение и разбор. Отделы делают разное, но смотрят
 * на одно и то же: что мне поручено, что висит в общей очереди, что я закрыл.
 * Три отдельных экрана означали бы три места, где чинить сортировку, и
 * сотрудника, который переучивается при переходе между отделами.
 *
 * Задачи выше лотов. Лот — это где мы в процессе, задача — что от меня хотят;
 * приходя утром, смотрят второе.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { auth } from "@/api/tender";
import {
  cardsApi,
  type Card,
  type Department,
  type Job,
  type TaskState,
} from "@/api/cards";
import { PageHeader } from "@/shell/AppShell";
import { ApiError } from "@/api/client";
import {
  Button,
  Card as Panel,
  EmptyState,
  Input,
  Page,
  Spinner,
  Tabs,
  cx,
  money,
} from "@/ui";

/** Какие лоты отдел считает своими: те, что стоят на его шаге. */
const OWN_STATUS: Record<Department, string[]> = {
  discussion: ["discussion"],
  analysis: ["new", "analysis"],
  supply: ["fulfilling"],
  legal: ["discussion"],
  // Технолог и сборщик смотрят лот там же, где ставят подпись: их работа —
  // ответить, подходит ли товар и соберём ли в срок, а не вести лот.
  technologist: ["approval", "ready"],
  assembler: ["approval", "ready"],
  approval: ["approval", "ready"],
  submission: ["ready", "awaiting", "won", "contract", "awaiting_payment"],
};

type Tab = "mine" | "queue" | "lots" | "desk" | "closed";

const TABS: { key: Tab; title: string }[] = [
  { key: "mine", title: "Мои задачи" },
  { key: "queue", title: "Очередь отдела" },
  { key: "lots", title: "Мои лоты" },
  { key: "desk", title: "Лоты отдела" },
  { key: "closed", title: "Закрытые" },
];

export function DeskPage({
  department,
  title,
  subtitle,
}: {
  department: Department;
  title: string;
  subtitle: string;
}) {
  const [tab, setTab] = useState<Tab>("mine");
  const cache = useQueryClient();

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });

  const { data: mine, isLoading: loadingMine } = useQuery({
    queryKey: ["desk-tasks", department, "mine"],
    queryFn: () => cardsApi.tasks({ department, mine: true }),
    refetchInterval: 60_000,
  });
  const { data: queue } = useQuery({
    queryKey: ["desk-tasks", department, "queue"],
    queryFn: () => cardsApi.tasks({ department, unassigned: true }),
    refetchInterval: 60_000,
  });
  const { data: closed } = useQuery({
    queryKey: ["desk-tasks", department, "closed"],
    queryFn: () => cardsApi.tasks({ department, mine: true, state: "done" }),
    enabled: tab === "closed",
  });
  const { data: cards } = useQuery({
    queryKey: ["cards"],
    queryFn: () => cardsApi.list(),
    refetchInterval: 60_000,
  });

  // Мои и отдельские лоты разведены. Одним списком «Мои лоты» показывал и
  // чужие — те, что просто стоят на шаге отдела, — и по нему нельзя было
  // ответить на вопрос, с которого начинают: что закреплено за мной.
  const mineLots = useMemo(
    () =>
      (cards ?? []).filter(
        (item) => me && (item.owner_id === me.id || item.manager_id === me.id),
      ),
    [cards, me],
  );
  const deskLots = useMemo(
    () =>
      (cards ?? []).filter((item) =>
        OWN_STATUS[department].includes(item.status),
      ),
    [cards, department],
  );

  const refresh = () =>
    void cache.invalidateQueries({ queryKey: ["desk-tasks", department] });

  const counts: Record<Tab, number> = {
    mine: mine?.length ?? 0,
    queue: queue?.length ?? 0,
    lots: mineLots.length,
    desk: deskLots.length,
    closed: closed?.length ?? 0,
  };

  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        action={
          counts.mine > 0 ? (
            <span className="text-sm text-ink-secondary">
              на вас <b className="font-semibold text-ink">{counts.mine}</b>
            </span>
          ) : (
            <span className="text-sm text-ink-muted">задач на вас нет</span>
          )
        }
      />

      <Page>
        <Tabs tabs={TABS} value={tab} counts={counts} onChange={setTab} />

        {tab === "lots" || tab === "desk" ? (
          <Lots
            lots={tab === "lots" ? mineLots : deskLots}
            mine={tab === "lots"}
          />
        ) : loadingMine ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем задачи…" />
          </Panel>
        ) : (
          <Jobs
            jobs={
              (tab === "mine" ? mine : tab === "queue" ? queue : closed) ?? []
            }
            tab={tab}
            onDone={refresh}
          />
        )}
      </Page>
    </>
  );
}

function Jobs({
  jobs,
  tab,
  onDone,
}: {
  jobs: Job[];
  tab: Tab;
  onDone: () => void;
}) {
  if (!jobs.length) {
    return (
      <Panel>
        <EmptyState
          title={
            tab === "mine"
              ? "На вас ничего не висит"
              : tab === "queue"
                ? "Очередь отдела пуста"
                : "Закрытых задач нет"
          }
          description={
            tab === "queue"
              ? "Ничьи задачи отдела появляются здесь. Их берут отсюда."
              : "Задачи заводятся с карточки лота."
          }
        />
      </Panel>
    );
  }

  return (
    <Panel className="overflow-hidden">
      <ul className="divide-y divide-hairline">
        {jobs.map((job) => (
          <JobRow key={job.id} job={job} onDone={onDone} />
        ))}
      </ul>
    </Panel>
  );
}

function JobRow({ job, onDone }: { job: Job; onDone: () => void }) {
  // Закрыть можно только с отчётом — та же дверь, что и в карточке лота.
  // Пока здесь закрывали одной кнопкой, правило в карточке обходилось: в
  // истории оставалось «закрыл», и ни премию посчитать, ни спросить, что
  // именно нашли.
  const [closing, setClosing] = useState(false);
  const [what, setWhat] = useState("");
  const [trouble, setTrouble] = useState("");

  const act = useMutation({
    mutationFn: (deed: "take" | TaskState) =>
      deed === "take"
        ? cardsApi.takeTask(job.id)
        : cardsApi.closeTask(job.id, deed, deed === "done" ? what : ""),
    onSuccess: () => {
      setClosing(false);
      setWhat("");
      setTrouble("");
      onDone();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
      <Link
        to={`/work/lots/${job.card_id}`}
        className="font-mono text-xs text-ink-muted hover:text-ink"
      >
        {job.card_code}
      </Link>

      <span className="min-w-0 flex-1">
        <span
          className={cx(
            "block truncate text-sm",
            job.state === "open" ? "text-ink" : "text-ink-muted line-through",
          )}
        >
          {job.title}
        </span>
        <span className="mt-0.5 block truncate text-xs text-ink-muted">
          {job.card_title}
        </span>
      </span>

      {job.left && job.state === "open" && (
        <span
          className={cx(
            "text-sm tabular-nums whitespace-nowrap",
            job.overdue
              ? "text-ink-muted line-through decoration-baseline"
              : job.burning
                ? "font-semibold text-critical"
                : "text-ink-secondary",
          )}
        >
          {job.left}
        </span>
      )}

      {job.state === "open" ? (
        <>
          {!job.assignee && (
            <button
              type="button"
              disabled={act.isPending}
              onClick={() => act.mutate("take")}
              className="rounded-[6px] border border-baseline px-2.5 py-1 text-xs text-ink transition hover:bg-plane disabled:opacity-45"
            >
              Взять себе
            </button>
          )}
          <button
            type="button"
            disabled={act.isPending}
            onClick={() => setClosing((was) => !was)}
            className="rounded-[6px] px-2.5 py-1 text-xs text-ink-muted transition hover:bg-plane hover:text-ink disabled:opacity-45"
          >
            {closing ? "Не закрывать" : "Закрыть"}
          </button>
        </>
      ) : (
        <span className="text-xs text-ink-muted">
          {job.result || "закрыта"}
        </span>
      )}

      {closing && (
        /* Во всю ширину строки: отчёт пишут фразой, а не словом, и поле в
           два сантиметра заставляет её сокращать до «сделал». */
        <div className="mt-1 flex w-full flex-wrap items-center gap-2">
          <Input
            value={what}
            onChange={(event) => setWhat(event.target.value)}
            placeholder="Что сделано: нашли поставщика, цена подтверждена, отправили запрос"
            className="min-w-64 flex-1"
            autoFocus
          />
          <Button
            variant="primary"
            onClick={() => act.mutate("done")}
            disabled={!what.trim() || act.isPending}
          >
            {act.isPending ? "Закрываем…" : "Закрыть задачу"}
          </Button>
        </div>
      )}

      {trouble && <p className="w-full text-xs text-critical">{trouble}</p>}
    </li>
  );
}

function Lots({ lots, mine }: { lots: Card[]; mine: boolean }) {
  if (!lots.length) {
    return (
      <Panel>
        <EmptyState
          title={mine ? "За вами лотов нет" : "На отделе лотов нет"}
          description={
            mine
              ? "Здесь те, где вы менеджер или текущий ответственный."
              : "Здесь те, что стоят на шаге вашего отдела, независимо от того, кто их ведёт."
          }
        />
      </Panel>
    );
  }

  return (
    <Panel className="overflow-hidden">
      <ul className="divide-y divide-hairline">
        {lots.map((card) => (
          <li key={card.id}>
            <Link
              to={`/work/lots/${card.id}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 transition hover:bg-plane"
            >
              <span className="font-mono text-xs text-ink-muted">
                {card.code}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-ink">
                  {card.title}
                </span>
                <span className="mt-0.5 block truncate text-xs text-ink-muted">
                  {card.customer || card.row_id}
                </span>
              </span>
              <span className="text-sm tabular-nums text-ink-secondary">
                {card.amount === null ? "—" : `${money(card.amount)} ₸`}
              </span>
              {card.left && (
                <span
                  className={cx(
                    "text-sm tabular-nums whitespace-nowrap",
                    card.overdue
                      ? "text-ink-muted"
                      : card.burning
                        ? "font-semibold text-critical"
                        : "text-ink-secondary",
                  )}
                >
                  {card.left}
                </span>
              )}
              <span className="w-28 truncate text-sm text-ink">
                {card.status_name}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Столы отделов. Обёртки задают только слова — работа у них одна. */
export function LegalDesk() {
  return (
    <DeskPage
      department="legal"
      title="Юристы"
      subtitle="Замечания, жалобы и всё, что подписывается от имени компании"
    />
  );
}

export function SupplyDesk() {
  return (
    <DeskPage
      department="supply"
      title="Снабжение"
      subtitle="Поиск товара, подтверждение цен и сроков поставки"
    />
  );
}

export function AnalysisDesk() {
  return (
    <DeskPage
      department="analysis"
      title="Разбор"
      subtitle="Себестоимость, маржа и решение, участвовать ли"
    />
  );
}
