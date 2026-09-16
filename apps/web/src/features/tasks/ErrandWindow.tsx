/**
 * Поручение целиком: что сделать, к какому сроку, и разговор о нём.
 *
 * Своё окно, а не карточка задачи отдела. У той правила очереди: «беру на
 * себя», «вернуть отделу», «задача у коллеги — дождитесь». У поручения
 * очереди нет вовсе — оно адресное, и эти кнопки предлагали бы действия,
 * которых здесь не бывает.
 *
 * Закрывает исполнитель или тот, кто поручил. Второе не поблажка: половина
 * просьб отпадает сама — «уже не нужно, нашли у себя», — и заставлять
 * исполнителя закрывать то, чего он не делал, значит получить отчёт «не
 * потребовалось» вместо отмены.
 */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { cardsApi, type Job } from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, cx } from "@/ui";
import { Avatar, Chip, Clock, Tick, span, stamp } from "@/features/cards/kit";
import { TaskTalk } from "@/features/cards/TaskTalk";
import { NewErrand } from "./NewErrand";

export function ErrandWindow({
  task,
  me,
  admin,
  onClose,
  onChanged,
  onDone,
}: {
  task: Job;
  me: string;
  admin: boolean;
  onClose: () => void;
  /** Задача изменилась, но окно остаётся: человек читает её дальше. */
  onChanged: (fresh: Job) => void;
  /** С задачей покончено — окно закрывается. */
  onDone: () => void;
}) {
  const [result, setResult] = useState("");
  const [editing, setEditing] = useState(false);
  const [trouble, setTrouble] = useState("");

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      // Пока открыта правка, Escape закрывает её, а не всё окно: иначе
      // отказ от одной опечатки уносит и прочитанную задачу.
      if (event.key === "Escape" && !editing) onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, editing]);

  const done = task.state !== "open";
  const mine = task.assignee_id === me;
  const author = task.author_id === me;
  const mayClose = mine || author || admin;

  const close = useMutation({
    mutationFn: (state: "done" | "cancelled") =>
      cardsApi.closeErrand(task.id, state, result.trim()),
    onSuccess: onDone,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const reopen = useMutation({
    mutationFn: () => cardsApi.closeErrand(task.id, "open"),
    onSuccess: onChanged,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  if (editing) {
    return (
      <NewErrand
        task={task}
        onClose={() => setEditing(false)}
        onAdded={(fresh) => {
          setEditing(false);
          onChanged(fresh);
        }}
      />
    );
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center bg-ink/40 px-4 py-10"
      role="dialog"
      aria-modal="true"
      aria-label="Поручение"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="max-h-full w-full max-w-[520px] overflow-y-auto">
        <div className="overflow-hidden rounded-[12px] border border-hairline bg-surface">
          <div className="flex items-center gap-2 border-b border-hairline px-3 py-2.5">
            <span className="text-[11.5px] text-ink-muted">Поручение</span>
            <span className="ml-auto flex items-center gap-2">
              {done ? (
                <Chip tone="ok">
                  <Tick size={9} /> Закрыта
                </Chip>
              ) : (
                task.due_at && <Clock due={task.due_at} />
              )}
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть окно"
                className="flex h-7 w-7 items-center justify-center rounded-[7px] text-ink-muted transition hover:bg-plane hover:text-ink"
              >
                ✕
              </button>
            </span>
          </div>

          <div className="px-3.5 py-3.5">
            <h3 className="text-[16px] leading-tight font-semibold tracking-[-0.015em] text-ink">
              {task.title}
            </h3>
            {task.body && (
              <p className="mt-2 text-[13px] leading-relaxed whitespace-pre-wrap text-ink-secondary">
                {task.body}
              </p>
            )}

            <dl className="mt-4 border-t border-hairline/70">
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
                  <span className="text-ink-secondary">—</span>
                )}
              </Row>
              <Row label="Поручил">
                <span className="tabular-nums">
                  {(task.author || "—").split(" ")[0]} ·{" "}
                  {stamp(task.created_at)}
                </span>
              </Row>
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
            {!done && mayClose && (
              <label className="mt-3.5 block">
                <span className="mb-1 block text-[11.5px] text-ink-muted">
                  Что сделали
                </span>
                <textarea
                  value={result}
                  onChange={(event) => setResult(event.target.value)}
                  rows={3}
                  placeholder="Коротко: к чему пришли. По записи «закрыл» через месяц не понять, что именно сделали."
                  className={cx(
                    "w-full resize-y rounded-[9px] border border-baseline bg-surface px-2.5 py-2",
                    "text-[13px] leading-relaxed text-ink placeholder:text-ink-muted",
                    "focus:border-series-1 focus:outline-none",
                  )}
                />
              </label>
            )}
          </div>

          {!done && mayClose && (
            <div className="flex flex-wrap gap-2 border-t border-hairline/70 px-3.5 py-3">
              <Button
                variant="primary"
                disabled={!result.trim() || close.isPending}
                onClick={() => close.mutate("done")}
                title={result.trim() ? undefined : "Напишите, что сделано"}
              >
                Закрыть задачу
              </Button>
              {/* Отмена — тоже с отчётом: «уже не нужно, нашли у себя» через
                  месяц отвечает на вопрос, почему её не сделали. */}
              {(author || admin) && (
                <Button
                  variant="secondary"
                  disabled={!result.trim() || close.isPending}
                  onClick={() => close.mutate("cancelled")}
                  title={
                    result.trim() ? undefined : "Напишите, почему отменяем"
                  }
                >
                  Отменить
                </Button>
              )}
              {(author || admin) && (
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  Поправить
                </Button>
              )}
            </div>
          )}

          {done && (author || admin) && (
            <div className="border-t border-hairline/70 px-3.5 py-3">
              <Button
                variant="secondary"
                disabled={reopen.isPending}
                onClick={() => reopen.mutate()}
              >
                Вернуть в работу
              </Button>
            </div>
          )}

          {!done && !mayClose && (
            <p className="border-t border-hairline/70 px-3.5 py-3 text-[12.5px] text-ink-secondary">
              Это поручение между {task.author || "коллегой"} и{" "}
              {task.assignee || "коллегой"}. Закрывают его они.
            </p>
          )}

          <div className="border-t border-hairline/70">
            <TaskTalk taskId={task.id} me={me} admin={admin} />
          </div>
        </div>

        {trouble && (
          <p
            className={cx(
              "mt-2 rounded-[9px] border border-critical/40 bg-critical/10",
              "px-3 py-2 text-[12.5px] text-ink",
            )}
          >
            {trouble}
          </p>
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2 border-b border-hairline/70 py-2 last:border-0">
      <dt className="w-28 shrink-0 text-[11.5px] text-ink-muted">{label}</dt>
      <dd className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 text-[12.5px] text-ink">
        {children}
      </dd>
    </div>
  );
}
