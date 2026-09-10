/**
 * Стол отдела: задачи и лоты, которые на нём.
 *
 * Один экран на юристов, снабжение и разбор. Отделы делают разное, но смотрят
 * на одно и то же: что мне поручено, что висит в общей очереди, что я закрыл.
 * Три отдельных экрана означали бы три места, где чинить сортировку, и
 * сотрудника, который переучивается при переходе между отделами.
 *
 * Только задачи. Списки лотов отсюда убраны: те же лоты, теми же колонками и
 * с тем же отбором по сотруднику лежат в «Лотах в работе», и второй их показ
 * означал бы второе место, где чинить сортировку. Стол отвечает на «что от
 * меня хотят», а не на «где мы в процессе».
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { auth } from "@/api/tender";
import { cardsApi, type Department, type Job } from "@/api/cards";
import { TaskWindow } from "./TaskWindow";
import { PageHeader } from "@/shell/AppShell";
import { ApiError } from "@/api/client";
import { Card as Panel, EmptyState, Page, Spinner, Tabs, cx } from "@/ui";

type Tab = "mine" | "queue" | "closed";

/** Что делают с открытой задачей. Отчёт нужен только закрытию. */
type Deed =
  { kind: "take" } | { kind: "release" } | { kind: "done"; result: string };

const TABS: { key: Tab; title: string }[] = [
  { key: "mine", title: "Мои задачи" },
  { key: "queue", title: "Очередь отдела" },
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
  // Читается сразу, а не по открытии вкладки. Числа стоят на самих вкладках,
  // и отложенный запрос показывал ноль у «Закрытых» до тех пор, пока по ней не
  // щёлкнут: человек видел пустой стол и уходил, не узнав, что за день закрыл
  // четыре задачи.
  const { data: closed } = useQuery({
    queryKey: ["desk-tasks", department, "closed"],
    queryFn: () => cardsApi.tasks({ department, mine: true, state: "done" }),
    refetchInterval: 60_000,
  });
  const refresh = () =>
    void cache.invalidateQueries({ queryKey: ["desk-tasks", department] });

  const counts: Record<Tab, number> = {
    mine: mine?.length ?? 0,
    queue: queue?.length ?? 0,
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

        {loadingMine ? (
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
  // Открытая задача хранится копией, а не поиском по списку: взятая уходит
  // из «Очереди отдела», и окно, смотрящее в список, опустело бы прямо под
  // рукой — посреди чтения задачи, которую человек только что взял.
  const [open, setOpen] = useState<Job | null>(null);
  const [trouble, setTrouble] = useState("");
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });

  const act = useMutation({
    mutationFn: (deed: Deed) =>
      deed.kind === "take"
        ? cardsApi.takeTask(open?.id ?? "")
        : deed.kind === "release"
          ? cardsApi.releaseTask(open?.id ?? "")
          : cardsApi.closeTask(open?.id ?? "", "done", deed.result),
    onSuccess: (fresh, deed) => {
      setTrouble("");
      // Взяли — окно остаётся с обновлённой задачей: человек продолжает её
      // читать и тут же пишет отчёт. Отдали или закрыли — закрываем: делать
      // с ней больше нечего.
      setOpen(deed.kind === "take" ? fresh : null);
      onDone();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const opened = open && (
    <TaskWindow
      task={open}
      me={me?.id ?? ""}
      busy={act.isPending}
      trouble={trouble}
      onClose={() => {
        setOpen(null);
        setTrouble("");
      }}
      onTake={() => act.mutate({ kind: "take" })}
      onRelease={() => act.mutate({ kind: "release" })}
      onFinish={(result) => act.mutate({ kind: "done", result })}
    />
  );

  if (!jobs.length) {
    return (
      <>
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
        {opened}
      </>
    );
  }

  return (
    <>
      <Panel className="overflow-hidden">
        <ul className="divide-y divide-hairline">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} onOpen={() => setOpen(job)} />
          ))}
        </ul>
      </Panel>
      {opened}
    </>
  );
}

/**
 * Строка задачи. Нажатие открывает её целиком.
 *
 * Кнопок в строке больше нет. Они позволяли взять и закрыть задачу, не
 * прочитав её: в заголовке «Найти товар и подтвердить цены · GZ000082» нет ни
 * товара, ни срока, ни того, что вернуть в ответе, — а отчёт о закрытии
 * писали по памяти о разговоре в коридоре.
 */
function JobRow({ job, onOpen }: { job: Job; onOpen: () => void }) {
  return (
    <li>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
        {/* Ссылка на лот отдельной кнопкой, а не внутри строки: вложенная в
            кнопку ссылка — неверная разметка, и нажатие на код открывало бы
            заодно окно задачи. */}
        <Link
          to={`/work/lots/${job.card_id}`}
          className="shrink-0 font-mono text-xs text-ink-muted hover:text-ink"
          title="Открыть лот"
        >
          {job.card_code}
        </Link>

        <button
          type="button"
          onClick={onOpen}
          className={cx(
            "flex min-w-0 flex-1 items-center gap-x-3 gap-y-1 text-left",
            "focus-visible:outline focus-visible:outline-2",
            "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
          )}
        >
          <span className="min-w-0 flex-1">
            <span
              className={cx(
                "block truncate text-sm",
                job.state === "open"
                  ? "text-ink"
                  : "text-ink-muted line-through",
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
                "shrink-0 text-sm tabular-nums whitespace-nowrap",
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

          {/* Кто держит задачу — в самой строке: очередь отдела читают
              глазами сверху вниз, и «свободна» должно быть видно без
              открытия. */}
          <span className="shrink-0 text-xs text-ink-muted">
            {job.state !== "open"
              ? "закрыта"
              : job.assignee
                ? job.assignee.split(" ")[0]
                : "свободна"}
          </span>
        </button>
      </div>
    </li>
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
