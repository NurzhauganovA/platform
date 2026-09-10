/**
 * Части правой колонки: рельса шагов, узел и карточка задачи.
 *
 * Рельсой, а не стопкой карточек. Шагов у лота семь, и семь одинаковых рамок
 * подряд — это список, по которому не видно хода: где были, где стоим, куда
 * дальше. Линия с отметками отвечает на это одним взглядом, а сама колонка
 * становится короче на треть — отделы свёрнуты, пока их не открыли.
 *
 * Отметка говорит состоянием, а не только цветом: у сделанного галочка, у
 * идущего толстое кольцо, у горящего — оно же красное и с числом рядом. Цвет
 * при дальтонизме не различить, а «сделано» и «горит» — это разные действия.
 *
 * Задача открывается на месте панели, а не окном. Окно закрывает собой лот,
 * ради которого задачу и читают: в ней написано «проверить пункты 4.1–4.6», а
 * пункты — на экране слева.
 */

import { useState, type ReactNode } from "react";
import { type Job } from "@/api/cards";
import { Button, cx } from "@/ui";
import {
  Avatar,
  Chevron,
  Chip,
  Clock,
  Tick,
  heat,
  short,
  span,
  stamp,
} from "./kit";

/** Состояние отметки на линии: сделано, идёт, горит, ещё не начато. */
export type Mark = "done" | "active" | "hot" | "idle";

/**
 * Один узел рельсы: отметка на линии и тело справа.
 *
 * Линия рисуется псевдоэлементами соседних ячеек, а не одной чертой поверх:
 * у первого узла она начинается от отметки, у последнего там же кончается —
 * иначе рельса торчит из-под первого и последнего кружка.
 */
export function Node({
  mark,
  title,
  right,
  meta,
  counts,
  open,
  onToggle,
  first,
  last,
  mine,
  children,
}: {
  mark: Mark;
  title: string;
  /** Что справа от названия: срок, плашка состояния или слово. */
  right?: ReactNode;
  meta?: ReactNode;
  counts?: ReactNode;
  open?: boolean;
  onToggle?: () => void;
  first?: boolean;
  last?: boolean;
  /** Узел моего отдела — подсвечен слева: свою очередь ищут глазами. */
  mine?: boolean;
  children?: ReactNode;
}) {
  const quiet = mark === "idle" && !meta;

  return (
    <div className="grid grid-cols-[34px_1fr]">
      <div className="relative flex justify-center pt-[15px]">
        <span
          aria-hidden
          className={cx(
            "absolute w-[1.5px] bg-hairline",
            first ? "top-[15px]" : "top-0",
            last ? "bottom-[calc(100%-15px)]" : "bottom-0",
          )}
        />
        <span
          className={cx(
            "relative z-[1] flex h-[17px] w-[17px] items-center justify-center rounded-full bg-surface",
            mark === "done"
              ? "border-[1.5px] border-good/50 bg-good/10 text-good"
              : mark === "active"
                ? "border-4 border-series-1"
                : mark === "hot"
                  ? "border-4 border-critical"
                  : "border-[1.5px] border-baseline",
          )}
        >
          {mark === "done" && <Tick />}
        </span>
      </div>

      <div
        className={cx(
          "border-b border-hairline/70 py-[11px] pr-3 pl-0.5 last:border-b-0",
          mine &&
            "-ml-[9px] border-l-2 border-l-series-1 bg-series-1/[0.04] pl-[9px]",
        )}
      >
        <button
          type="button"
          onClick={onToggle}
          disabled={!onToggle}
          aria-expanded={onToggle ? Boolean(open) : undefined}
          className={cx(
            "flex min-h-[22px] w-full items-center justify-between gap-2 text-left",
            onToggle && "cursor-pointer",
          )}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            {onToggle && <Chevron open={Boolean(open)} />}
            <span
              className={cx(
                "truncate text-[13.5px] font-semibold tracking-[-0.01em]",
                quiet ? "text-ink-muted" : "text-ink",
              )}
            >
              {title}
            </span>
          </span>
          {right}
        </button>

        {(meta || counts) && (
          <div className="mt-0.5 pl-[17px] text-[12.5px] text-ink-secondary">
            {meta}
            {counts && (
              <div className={cx("tabular-nums", meta && "mt-0.5")}>
                {counts}
              </div>
            )}
          </div>
        )}

        {open && children}
      </div>
    </div>
  );
}

/**
 * Строка задачи в развёрнутом узле.
 *
 * Кружок слева у каждой задачи, а не галочка у одних закрытых. Пока у
 * открытых там было пусто, список читался как сплошной текст: сколько задач в
 * отделе, приходилось считать строки глазами. Кружок даёт счёт с одного
 * взгляда, а закрытая отличается не только серым текстом — в кружке галочка.
 *
 * Открытая задача лежит на своей подложке, закрытая — на голом фоне. Разница
 * не декоративная: очередь работы — это то, что не сделано, и на неё смотрят;
 * закрытые остаются для вопроса «а что там было», который задают потом.
 */
export function TaskLine({ task, onOpen }: { task: Job; onOpen: () => void }) {
  const done = task.state === "done";
  const who = task.assignee || task.done_by;

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cx(
        "grid w-full grid-cols-[16px_1fr_auto] items-center gap-2.5 rounded-[9px] px-2 py-2",
        "text-left transition",
        done
          ? "hover:bg-ink/[0.04]"
          : "border border-hairline bg-ink/[0.04] hover:bg-ink/[0.07]",
        "focus-visible:outline focus-visible:outline-2",
        "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
      )}
    >
      <Ring done={done} />
      <span className="min-w-0">
        <span
          className={cx(
            "block truncate text-[12.5px] leading-[1.35]",
            done ? "text-ink-muted" : "font-medium text-ink",
          )}
        >
          {task.title}
        </span>
        <span className="mt-px block truncate text-[11.5px] text-ink-muted">
          {done
            ? `${(task.done_by || "закрыта").split(" ")[0]}${task.done_at ? ` · ${stamp(task.done_at)}` : ""}`
            : task.taken_at
              ? (who || "взята").split(" ")[0]
              : "свободна"}
        </span>
      </span>
      {!done && task.due_at && (
        <span
          className={cx(
            "text-[11.5px] font-medium whitespace-nowrap tabular-nums",
            heat(task.due_at) === "hot"
              ? "text-critical"
              : heat(task.due_at) === "warm"
                ? "text-ink"
                : "text-ink-secondary",
          )}
        >
          {short(task.due_at)}
        </span>
      )}
    </button>
  );
}

/** Кружок задачи: пустой у открытой, с галочкой у закрытой. */
function Ring({ done }: { done: boolean }) {
  return (
    <span
      aria-hidden
      className={cx(
        "flex h-4 w-4 items-center justify-center rounded-full",
        done
          ? "border-[1.5px] border-good/50 bg-good/10 text-good"
          : "border-[1.5px] border-baseline bg-surface",
      )}
    >
      {done && <Tick size={9} />}
    </span>
  );
}

/**
 * Карточка задачи вместо панели.
 *
 * Вместо, а не поверх: задача читается вместе с лотом, а окно закрывает собой
 * ровно то, о чём в ней написано.
 *
 * Взятие — одно нажатие и без вопросов. Срок называть не надо: его назначил
 * тот, кто задачу завёл, — он и знает, к какому часу нужен ответ. Пока срок
 * называл берущий, задача «к 16:00», взятая в 15:50 «на три часа», молча
 * становилась задачей «до 18:50», и подача уезжала за срок приёма.
 *
 * Закрыть без отчёта нельзя. Поле было в базе с самого начала, но его никто не
 * спрашивал, и в истории оставалось «закрыл»: ни премию посчитать, ни спросить,
 * что именно нашли.
 */
export function TaskCard({
  task,
  me,
  deskName,
  busy,
  backLabel = "Назад к шагам лота",
  lot,
  onBack,
  onTake,
  onRelease,
  onClose,
}: {
  task: Job;
  me: string;
  deskName: string;
  busy: boolean;
  /** Куда ведёт стрелка назад. На столе отдела это не шаги лота, а список. */
  backLabel?: string;
  /** Из какого лота задача. В колонке лота это и так известно, а на столе
   *  отдела задача без лота — это работа неизвестно над чем. */
  lot?: ReactNode;
  onBack: () => void;
  onTake: () => void;
  onRelease: () => void;
  onClose: (result: string) => void;
}) {
  const [result, setResult] = useState("");

  const done = task.state === "done";
  const free = !task.taken_at;
  const mine = task.assignee_id === me;

  return (
    <div className="overflow-hidden rounded-[12px] border border-hairline bg-surface">
      <div className="flex items-center gap-2 border-b border-hairline px-3 py-2.5">
        <button
          type="button"
          onClick={onBack}
          aria-label={backLabel}
          className="flex h-7 w-7 items-center justify-center rounded-[7px] text-ink-muted transition hover:bg-plane hover:text-ink"
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden
          >
            <path
              d="M10 3 5 8l5 5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <span className="text-[11.5px] text-ink-muted">{deskName}</span>
        <span className="ml-auto">
          {done ? (
            <Chip tone="ok">
              <Tick size={9} /> Закрыта
            </Chip>
          ) : (
            task.due_at && <Clock due={task.due_at} />
          )}
        </span>
      </div>

      <div className="px-3.5 py-3.5">
        <h3 className="text-[16px] leading-tight font-semibold tracking-[-0.015em] text-ink">
          {task.title}
        </h3>
        {lot && <div className="mt-1 text-[12.5px] text-ink-muted">{lot}</div>}
        {task.body && (
          <p className="mt-2 text-[13px] leading-relaxed whitespace-pre-wrap text-ink-secondary">
            {task.body}
          </p>
        )}

        <dl className="mt-4 border-t border-hairline/70">
          {/* Сколько дано и до какого часа — одной строкой. «До 16:30» без
              «трёх часов» не говорит, много это или мало, а «три часа» без
              часа не говорит, к какому времени сдавать. */}
          <Row label="Сделать до">
            <span className="tabular-nums">
              {task.due_at ? stamp(task.due_at) : "—"}
            </span>
            {task.due_at && task.created_at && (
              <span className="text-ink-muted">
                · дано {span(task.created_at, task.due_at)}
              </span>
            )}
          </Row>
          <Row label="Исполнитель">
            {task.assignee ? (
              <>
                <Avatar name={task.assignee} />
                {task.assignee}
              </>
            ) : (
              <span className="text-ink-secondary">любой в отделе</span>
            )}
          </Row>
          {task.author && (
            <Row label="Поставил">
              <span className="tabular-nums">
                {task.author.split(" ")[0]} · {stamp(task.created_at)}
              </span>
            </Row>
          )}
          {done && (
            <Row label="Закрыл">
              <span className="tabular-nums">
                {(task.done_by || "—").split(" ")[0]}
                {task.done_at && ` · ${stamp(task.done_at)}`}
              </span>
            </Row>
          )}
        </dl>

        {done && task.result && (
          <div className="mt-3 rounded-[9px] bg-good/10 px-3 py-2.5">
            <div className="text-[11.5px] text-good">Результат</div>
            <div className="mt-1 text-[12.5px] leading-relaxed text-ink">
              {task.result}
            </div>
          </div>
        )}

        {/* Отчёт спрашивается до нажатия, а не после: окно с вопросом «что
            сделано» поверх уже нажатой кнопки человек закрывает крестиком. */}
        {!done && mine && (
          <label className="mt-3.5 block">
            <span className="mb-1 block text-[11.5px] text-ink-muted">
              Что сделали
            </span>
            <textarea
              value={result}
              onChange={(event) => setResult(event.target.value)}
              rows={3}
              placeholder="Коротко: к чему пришли. Останется в истории лота."
              className={cx(
                "w-full resize-y rounded-[9px] border border-baseline bg-surface px-2.5 py-2",
                "text-[13px] leading-relaxed text-ink placeholder:text-ink-muted",
                "focus:border-series-1 focus:outline-none",
              )}
            />
          </label>
        )}
      </div>

      {!done && free && (
        <div className="border-t border-hairline/70 px-3.5 py-3">
          <Button variant="primary" disabled={busy} onClick={onTake}>
            {busy ? "Берём…" : "Беру на себя"}
          </Button>
          <p className="mt-1.5 text-[11.5px] text-ink-muted">
            Задача на весь отдел — берёт тот, кто свободен. Срок уже назначен и
            от взятия не меняется.
          </p>
        </div>
      )}

      {!done && mine && (
        <div className="flex flex-wrap gap-2 border-t border-hairline/70 px-3.5 py-3">
          <Button
            variant="primary"
            disabled={!result.trim() || busy}
            onClick={() => onClose(result.trim())}
            title={result.trim() ? undefined : "Напишите, что сделано"}
          >
            Закрыть задачу
          </Button>
          <Button variant="secondary" disabled={busy} onClick={onRelease}>
            Вернуть отделу
          </Button>
        </div>
      )}

      {!done && !free && !mine && (
        <p className="border-t border-hairline/70 px-3.5 py-3 text-[12.5px] text-ink-secondary">
          Задача у {task.assignee || "коллеги"}. Дождитесь или попросите вернуть
          в очередь.
        </p>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-hairline/70 py-2 last:border-b-0">
      <dt className="text-[11.5px] text-ink-muted">{label}</dt>
      <dd className="inline-flex items-center gap-1.5 text-right text-[12.5px] text-ink">
        {children}
      </dd>
    </div>
  );
}
