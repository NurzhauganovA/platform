/**
 * Окно «Поручить задачу» — и оно же правка поручения.
 *
 * Одна форма на оба случая: поля те же, и вторая копия разошлась бы с первой
 * на первой же правке — обычно тем, что в одной из них забыли срок.
 *
 * Исполнитель обязателен, и это не формальность. Задача вне лота не попадает
 * ни в одну очередь: ничью её никто не подберёт, и лежать она будет ровно до
 * того дня, когда о ней спросят.
 *
 * Срок обязателен по той же причине, что и в задачах по лоту: без него задача
 * не горит и не всплывает никогда. Ставит его тот, кто поручает, — он знает,
 * к какому часу нужен ответ.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { cardsApi, type Job } from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, cx } from "@/ui";

/** Сколько времени даётся — быстрым выбором. Набирать дату мышью ради «трёх
 *  часов» — четыре нажатия вместо одного. */
const SPANS: { hours: number; title: string }[] = [
  { hours: 1, title: "1 час" },
  { hours: 3, title: "3 часа" },
  { hours: 24, title: "Сутки" },
  { hours: 72, title: "3 дня" },
];

const DEFAULT_HOURS = 24;

export function NewErrand({
  task,
  onClose,
  onAdded,
}: {
  /** Что правим. Пусто — заводим новое. */
  task?: Job;
  onClose: () => void;
  onAdded: (task: Job) => void;
}) {
  const first = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState(task?.title ?? "");
  const [body, setBody] = useState(task?.body ?? "");
  const [who, setWho] = useState(task?.assignee_id ?? "");
  const [due, setDue] = useState(() =>
    task?.due_at ? local(new Date(task.due_at)) : later(DEFAULT_HOURS),
  );
  const [pick, setPick] = useState<number | null>(task ? null : DEFAULT_HOURS);
  const [trouble, setTrouble] = useState("");

  const { data: people } = useQuery({
    queryKey: ["people"],
    queryFn: cardsApi.people,
    staleTime: 10 * 60 * 1000,
  });

  useEffect(() => {
    first.current?.focus();
    const press = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [onClose]);

  const save = useMutation({
    mutationFn: () =>
      task
        ? cardsApi.editErrand(task.id, {
            title: title.trim(),
            body: body.trim(),
            assignee_id: who,
            change_assignee: who !== task.assignee_id,
            // Местное время браузера и есть время отдела: платформой
            // пользуются в одном поясе, и «до 16:00» значит одно и то же у
            // всех.
            due_at: due ? new Date(due).toISOString() : null,
            change_due: true,
          })
        : cardsApi.addErrand({
            title: title.trim(),
            body: body.trim(),
            assignee_id: who,
            due_at: due ? new Date(due).toISOString() : null,
          }),
    onSuccess: onAdded,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не завелась"),
  });

  const ready = title.trim() !== "" && who !== "" && due !== "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4 py-4"
      role="dialog"
      aria-modal="true"
      aria-label={task ? "Правка поручения" : "Новое поручение"}
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="max-h-[92vh] w-full max-w-[470px] overflow-auto rounded-[14px] border border-hairline bg-surface shadow-[0_18px_48px_rgba(14,22,32,.24)]">
        <header className="flex items-center justify-between gap-3 px-[18px] pt-[15px]">
          <h2 className="text-[15.5px] font-semibold tracking-[-0.015em] text-ink">
            {task ? "Поправить поручение" : "Поручить задачу"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="flex h-7 w-7 items-center justify-center rounded-[7px] text-ink-muted transition hover:bg-plane hover:text-ink"
          >
            ✕
          </button>
        </header>

        <div className="flex flex-col gap-3 px-[18px] pt-3.5 pb-1">
          <Field label="Что сделать" id="errand-title">
            <input
              id="errand-title"
              ref={first}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Собрать доверенности на подпись"
              className={INPUT}
            />
          </Field>

          <Field label="Описание" id="errand-body">
            <textarea
              id="errand-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={4}
              placeholder="Что именно нужно, где взять, что вернуть в ответе."
              className={cx(INPUT, "min-h-24 resize-y leading-relaxed")}
            />
          </Field>

          <Field label="Кому" id="errand-who">
            <select
              id="errand-who"
              value={who}
              onChange={(event) => setWho(event.target.value)}
              className={cx(INPUT, "h-9 py-0")}
            >
              {/* Пустой выбор остаётся в списке: без него первый в алфавите
                  человек оказывался выбранным сам собой, и поручение уходило
                  ему по невнимательности. */}
              <option value="">Выберите сотрудника</option>
              {(people ?? []).map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Сделать до" id="errand-due">
            <input
              id="errand-due"
              type="datetime-local"
              value={due}
              onChange={(event) => {
                setDue(event.target.value);
                setPick(null);
              }}
              className={cx(INPUT, "h-9 py-0 tabular-nums")}
            />
            <div className="mt-1.5 flex flex-wrap gap-1">
              {SPANS.map((item) => (
                <button
                  key={item.hours}
                  type="button"
                  onClick={() => {
                    setDue(later(item.hours));
                    setPick(item.hours);
                  }}
                  className={cx(
                    "rounded-[6px] border px-2 py-0.5 text-[12px] transition",
                    pick === item.hours
                      ? "border-series-1 bg-series-1/10 font-medium text-series-1"
                      : "border-hairline text-ink-secondary hover:bg-plane",
                  )}
                >
                  {item.title}
                </button>
              ))}
            </div>
          </Field>

          {trouble && <p className="text-[12.5px] text-critical">{trouble}</p>}
        </div>

        <footer className="flex justify-end gap-2 px-[18px] pt-3.5 pb-4">
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            disabled={!ready || save.isPending}
            onClick={() => save.mutate()}
            title={ready ? undefined : "Нужны название, исполнитель и срок"}
          >
            {save.isPending ? "Сохраняем…" : task ? "Сохранить" : "Поручить"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

const INPUT = cx(
  "w-full rounded-[9px] border border-hairline bg-surface px-2.5 py-2",
  "text-[13.5px] text-ink placeholder:text-ink-muted",
  "focus:border-series-1 focus:outline-none",
);

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-[12px] text-ink-secondary"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

/** Время через столько-то часов в том виде, какой понимает поле ввода. */
function later(hours: number): string {
  return local(new Date(Date.now() + hours * 60 * 60 * 1000));
}

function local(at: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
}
