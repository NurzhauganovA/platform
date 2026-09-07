/**
 * Задачи лота.
 *
 * Открытые сверху и всегда видны, закрытые прячутся за счётчиком: очередь
 * работы — это то, что не сделано, а закрытые смотрят редко и по делу.
 *
 * Заводится задача одной строкой. Форма из пяти полей на действие, которое
 * делают по десять раз в день, — это форма, которой не пользуются: пишут в
 * мессенджер, как писали.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cardsApi,
  type Card,
  type Department,
  type Job,
  type Person,
} from "@/api/cards";
import { Button, Spinner, cx } from "@/ui";

const DEPARTMENTS: { key: Department; title: string }[] = [
  { key: "discussion", title: "Обсуждение" },
  { key: "analysis", title: "Разбор" },
  { key: "supply", title: "Снабжение" },
  { key: "legal", title: "Юристы" },
  { key: "approval", title: "Согласование" },
  { key: "submission", title: "Подача" },
];

export function Tasks({ card, people }: { card: Card; people: Person[] }) {
  const cache = useQueryClient();
  const [closed, setClosed] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["card-tasks", card.id, closed],
    queryFn: () =>
      cardsApi.tasks({ card_id: card.id, state: closed ? "done" : "open" }),
  });

  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["card-tasks", card.id] });
    void cache.invalidateQueries({ queryKey: ["card", card.id] });
  };

  return (
    <section className="rounded-[10px] border border-hairline bg-surface">
      <header className="flex items-baseline justify-between gap-4 border-b border-hairline px-4 py-2.5">
        <h2 className="text-sm font-semibold text-ink">Задачи</h2>
        <nav className="flex gap-0.5">
          <Tab on={!closed} onClick={() => setClosed(false)}>
            Актуальные {card.open_tasks > 0 && <Count n={card.open_tasks} />}
          </Tab>
          <Tab on={closed} onClick={() => setClosed(true)}>
            Закрытые {card.done_tasks > 0 && <Count n={card.done_tasks} />}
          </Tab>
        </nav>
      </header>

      <Add card={card} people={people} onDone={refresh} />

      {isLoading ? (
        <div className="px-4 py-4">
          <Spinner label="Читаем задачи…" />
        </div>
      ) : !data?.length ? (
        <p className="px-4 py-6 text-center text-sm text-ink-muted">
          {closed ? "Закрытых задач нет" : "Открытых задач нет"}
        </p>
      ) : (
        <ul className="divide-y divide-hairline">
          {data.map((task) => (
            <Row key={task.id} task={task} onDone={refresh} />
          ))}
        </ul>
      )}
    </section>
  );
}

function Tab({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "rounded-[6px] px-2.5 py-1 text-xs transition",
        on ? "bg-ink text-surface" : "text-ink-secondary hover:bg-plane",
      )}
    >
      {children}
    </button>
  );
}

function Count({ n }: { n: number }) {
  return <span className="ml-1 tabular-nums opacity-70">{n}</span>;
}

function Add({
  card,
  people,
  onDone,
}: {
  card: Card;
  people: Person[];
  onDone: () => void;
}) {
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState<Department | "">("");
  const [assignee, setAssignee] = useState("");

  const add = useMutation({
    mutationFn: () =>
      cardsApi.addTask(card.id, {
        title,
        department: department || undefined,
        assignee_id: assignee || null,
      }),
    onSuccess: () => {
      setTitle("");
      setAssignee("");
      onDone();
    },
  });

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-hairline bg-plane px-4 py-2.5">
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && title.trim()) add.mutate();
        }}
        placeholder="Что сделать"
        className={cx(
          "h-8 min-w-0 flex-1 rounded-[8px] border border-baseline bg-surface px-3",
          "text-sm text-ink placeholder:text-ink-muted",
          "focus:border-series-1 focus:outline-none",
        )}
      />
      <select
        value={department}
        onChange={(event) =>
          setDepartment(event.target.value as Department | "")
        }
        className="h-8 rounded-[8px] border border-baseline bg-surface px-2 text-sm text-ink focus:border-series-1 focus:outline-none"
      >
        {/* Пусто — отдел берётся тот, у кого лот сейчас. Чаще всего задачу
            заводят себе, и переспрашивать об этом каждый раз лишнее. */}
        <option value="">Отдел по статусу</option>
        {DEPARTMENTS.map((item) => (
          <option key={item.key} value={item.key}>
            {item.title}
          </option>
        ))}
      </select>
      <select
        value={assignee}
        onChange={(event) => setAssignee(event.target.value)}
        className="h-8 max-w-44 rounded-[8px] border border-baseline bg-surface px-2 text-sm text-ink focus:border-series-1 focus:outline-none"
      >
        <option value="">В очередь отдела</option>
        {people.map((person) => (
          <option key={person.id} value={person.id}>
            {person.name}
          </option>
        ))}
      </select>
      <Button
        variant="secondary"
        disabled={!title.trim() || add.isPending}
        onClick={() => add.mutate()}
      >
        {add.isPending ? "Заводим…" : "Добавить"}
      </Button>
    </div>
  );
}

/**
 * Окно закрытия задачи.
 *
 * Окном, а не строкой в списке: закрытие — единственное место, где
 * исполнитель рассказывает, что сделал, и втиснутое между соседними задачами
 * поле подсказывает написать два слова. Текст попадает в историю лота, и
 * через месяц по нему отвечают, чем всё кончилось.
 */
function CloseTask({
  task,
  value,
  onChange,
  onClose,
  onDone,
  busy,
}: {
  task: Job;
  value: string;
  onChange: (next: string) => void;
  onClose: () => void;
  onDone: () => void;
  busy: boolean;
}) {
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center bg-ink/25 px-6 py-28"
      role="dialog"
      aria-modal="true"
      aria-label="Закрыть задачу"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-[12px] border border-hairline bg-surface shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-baseline justify-between gap-4 border-b border-hairline px-5 py-3">
          <h2 className="text-[15px] font-semibold text-ink">Закрыть задачу</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-series-1 hover:underline"
          >
            Отмена
          </button>
        </header>

        <div className="space-y-3 px-5 py-4">
          <div>
            <p className="text-sm font-medium text-ink">{task.title}</p>
            <p className="mt-0.5 text-xs text-ink-muted">
              {task.department_name}
              {task.due_at &&
                ` · срок ${new Date(task.due_at).toLocaleString("ru", {
                  day: "2-digit",
                  month: "2-digit",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}`}
              {task.assignee && ` · ${task.assignee}`}
            </p>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-sm text-ink">Что сделано</span>
            <textarea
              value={value}
              onChange={(event) => onChange(event.target.value)}
              rows={4}
              autoFocus
              placeholder="Одно-два предложения: что проверили, что нашли, что передали дальше"
              className={cx(
                "w-full resize-y rounded-[8px] border border-baseline bg-surface px-3 py-2",
                "text-sm text-ink placeholder:text-ink-muted",
                "focus:border-series-1 focus:outline-none",
              )}
            />
          </label>

          <p className="text-xs text-ink-muted">
            {value.trim()
              ? "Текст сохраняется в задаче и попадает в историю лота — по нему через месяц видно, чем всё кончилось."
              : "Без отчёта задача не закроется: по записи «закрыл» через месяц не понять, что именно нашли и кому за это платить."}
          </p>
        </div>

        <footer className="flex gap-2 border-t border-hairline px-5 py-3">
          {/* Пустой отчёт сервер не примет. Гасим кнопку до нажатия: отказ
              после — это набранное впустую окно и вопрос «а что не так». */}
          <Button
            variant="primary"
            onClick={onDone}
            disabled={busy || !value.trim()}
          >
            Закрыть задачу
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
        </footer>
      </div>
    </div>
  );
}

function Row({ task, onDone }: { task: Job; onDone: () => void }) {
  // Что сделано — пишет исполнитель, а не догадывается тот, кто задачу завёл.
  // Раньше задача закрывалась одной кнопкой, и в истории оставалось только
  // «закрыл»: по такой записи ни премию посчитать, ни спросить, что именно
  // нашли.
  const [closing, setClosing] = useState(false);
  const [what, setWhat] = useState("");

  const close = useMutation({
    mutationFn: () => cardsApi.closeTask(task.id, "done", what),
    onSuccess: () => {
      setClosing(false);
      setWhat("");
      onDone();
    },
  });
  const reopen = useMutation({
    mutationFn: () => cardsApi.closeTask(task.id, "open"),
    onSuccess: onDone,
  });
  const take = useMutation({
    mutationFn: () => cardsApi.takeTask(task.id),
    onSuccess: onDone,
  });

  const busy = close.isPending || reopen.isPending || take.isPending;

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
      <span className="text-xs whitespace-nowrap text-ink-muted">
        {task.department_name}
      </span>
      <span
        className={cx(
          "min-w-0 flex-1 truncate text-sm",
          task.state === "open" ? "text-ink" : "text-ink-muted line-through",
        )}
      >
        {task.title}
      </span>

      {task.left && task.state === "open" && (
        <span
          className={cx(
            "text-sm tabular-nums whitespace-nowrap",
            task.overdue
              ? "text-ink-muted"
              : task.burning
                ? "font-medium text-critical"
                : "text-ink-secondary",
          )}
        >
          {task.left}
        </span>
      )}

      {task.assignee ? (
        <span className="truncate text-sm text-ink-secondary">
          {task.assignee}
        </span>
      ) : task.state === "open" ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => take.mutate()}
          className="rounded-[6px] border border-baseline px-2 py-0.5 text-xs text-ink transition hover:bg-plane disabled:opacity-45"
        >
          Взять себе
        </button>
      ) : null}

      {task.state === "open" ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => setClosing(true)}
          className="rounded-[6px] px-2 py-0.5 text-xs text-ink-muted transition hover:bg-plane hover:text-ink disabled:opacity-45"
        >
          Закрыть
        </button>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={() => reopen.mutate()}
          className="rounded-[6px] px-2 py-0.5 text-xs text-ink-muted transition hover:bg-plane hover:text-ink disabled:opacity-45"
        >
          Открыть
        </button>
      )}

      {/* Итог задачи виден и после закрытия: это ответ на вопрос «а что там
          было», который задают через месяц. */}
      {task.result && !closing && (
        <p className="w-full text-xs text-ink-secondary">{task.result}</p>
      )}

      {closing && (
        <CloseTask
          task={task}
          value={what}
          onChange={setWhat}
          onClose={() => {
            setClosing(false);
            setWhat("");
          }}
          onDone={() => close.mutate()}
          busy={busy}
        />
      )}
    </li>
  );
}
