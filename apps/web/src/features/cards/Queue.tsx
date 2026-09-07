/**
 * Задачи по лоту: сводка в правом столбце и полная очередь окном.
 *
 * Сводка отвечает на «что ещё не сделано» — вопрос, который задают на любой
 * вкладке, а не только на той, где очередь. Числа по шагам стоят в блоках
 * шагов рядом, но там они по одному шагу за раз: «сколько всего висит и что
 * горит» из пяти чисел взглядом не складывается.
 *
 * Ближайшие три задачи строками, остальное — окном. Окном, а не разворотом в
 * колонке: заводя задачу, человек выбирает отдел, исполнителя и срок, и
 * делать это в колонке шириной в триста точек значит прокручивать форму
 * внутри колонки внутри страницы.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cardsApi, type Card, type Job, type Person } from "@/api/cards";
import { Button, Card as Panel, cx } from "@/ui";
import { Tasks } from "./Tasks";

/** Сколько задач показывать в столбце. Дальше — окном. */
const SHOWN = 3;

export function Queue({ card, people }: { card: Card; people: Person[] }) {
  const [open, setOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ["card-tasks", card.id],
    queryFn: () => cardsApi.tasks({ card_id: card.id }),
    staleTime: 15_000,
  });

  const live = (data ?? []).filter((task) => task.state === "open");
  const burning = live.filter((task) => task.burning || task.overdue).length;

  return (
    <>
      <Panel>
        <div className="flex items-baseline gap-x-2 border-b border-hairline px-4 py-2.5">
          <h2 className="text-sm font-semibold text-ink">Задачи</h2>
          <p className="flex-1 text-xs text-ink-muted">
            {live.length === 0
              ? "ничего не ждёт"
              : `${live.length} открытых${burning ? ` · ${burning} горит` : ""}`}
          </p>
          {/* Цвет не сам по себе: рядом слово «горит» из подписи выше. */}
          {burning > 0 && (
            <span aria-hidden className="text-xs text-critical">
              ◑
            </span>
          )}
        </div>

        {live.length > 0 && (
          <ul className="divide-y divide-hairline">
            {live.slice(0, SHOWN).map((task) => (
              <Line key={task.id} task={task} onOpen={() => setOpen(true)} />
            ))}
          </ul>
        )}

        <div className="px-4 py-2.5">
          {/* Залитой кнопкой, а не рамкой: заводить задачу — то, ради чего
              сюда и смотрят, а серая кнопка среди серых рамок теряется. */}
          <Button
            variant="primary"
            onClick={() => setOpen(true)}
            className="w-full"
          >
            {live.length > SHOWN
              ? `Все задачи · ${live.length}`
              : "Задачи и отчёты"}
          </Button>
        </div>
      </Panel>

      {open && (
        <Window card={card} people={people} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

/** Одна строка очереди: чья, о чём и сколько осталось. */
function Line({ task, onOpen }: { task: Job; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={cx(
          "w-full px-4 py-2 text-left transition hover:bg-plane",
          "focus-visible:outline focus-visible:outline-2",
          "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
        )}
      >
        <span className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-sm text-ink">
            {task.title}
          </span>
          {(task.overdue || task.burning) && (
            <span
              className={cx(
                "shrink-0 text-xs whitespace-nowrap",
                task.overdue ? "text-ink-muted" : "font-medium text-critical",
              )}
            >
              {task.overdue ? "срок прошёл" : task.left}
            </span>
          )}
        </span>
        <span className="mt-0.5 block truncate text-xs text-ink-muted">
          {task.department_name}
          {task.assignee && ` · ${task.assignee}`}
        </span>
      </button>
    </li>
  );
}

/**
 * Окно с полной очередью.
 *
 * Внутри тот же блок задач, что был вкладкой: заведение, закрытие с отчётом,
 * закрытые. Переписывать его под колонку значило бы завести вторые правила
 * закрытия задачи — и однажды разойтись с первыми.
 */
export function Window({
  card,
  people,
  onClose,
}: {
  card: Card;
  people: Person[];
  onClose: () => void;
}) {
  // Escape закрывает: окно открывают из колонки мимоходом, и тянуться мышью к
  // крестику ради взгляда на список — лишнее движение.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center bg-ink/25 px-6 py-16"
      role="dialog"
      aria-modal="true"
      aria-label="Задачи по лоту"
      onClick={onClose}
    >
      <div
        className="flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-[12px] border border-hairline bg-surface shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-hairline px-5 py-3">
          <h2 className="text-[15px] font-semibold text-ink">
            Задачи · {card.code}
          </h2>
          <p className="flex-1 text-sm text-ink-muted">
            очередь работы по отделам
          </p>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-[8px] px-2 py-1 text-ink-muted transition hover:bg-plane hover:text-ink"
          >
            ✕
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <Tasks card={card} people={people} />
        </div>
      </div>
    </div>
  );
}
