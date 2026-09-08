/**
 * Окно «Новая задача».
 *
 * Пятью полями, а не одной строкой. Строка «что сделать» рядом с двумя
 * списками заводила задачи без срока и без описания: исполнитель получал
 * «Проверить спецификацию» и шёл спрашивать, что именно проверить, — то есть
 * ровно тот разговор, ради ухода от которого очередь и заводили. Срок
 * обязателен по той же причине: задача без срока не горит и не всплывает
 * никогда.
 *
 * Окном, а не разворотом в колонке. Колонка шириной в триста точек: форма из
 * пяти полей прокручивалась бы внутри колонки внутри страницы, а заводят
 * задачу глядя на разбор — тот самый, что открыт слева.
 *
 * Куда — двумя группами. Этап лота и отдел устроены по-разному: задачу этапа
 * берёт кто угодно, задачу отдела — только этот отдел, и слитый список из
 * восьми строк эту разницу прятал.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cardsApi, type Card, type Department, type Person } from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, cx } from "@/ui";

/** Этапы лота: их задачу берёт кто угодно. */
const STAGES: { key: Department; title: string }[] = [
  { key: "discussion", title: "Обсуждение" },
  { key: "analysis", title: "Разбор" },
  { key: "approval", title: "Согласование" },
  { key: "submission", title: "Подача" },
];

/** Отделы: задача адресуется отделу, а не человеку — уволившийся иначе
 *  уносит очередь с собой. */
const DESKS: { key: Department; title: string }[] = [
  { key: "legal", title: "Юристы" },
  { key: "supply", title: "Снабжение" },
  { key: "technologist", title: "Технолог" },
  { key: "assembler", title: "Сборщик" },
];

/**
 * Сколько времени даётся на задачу — быстрым выбором.
 *
 * Срок ставит тот, кто задачу завёл: он знает, к какому часу нужен ответ.
 * Берущий его не двигает, поэтому здесь это не формальность, а само задание:
 * «до 16:00» и «до конца дня» — разная работа.
 *
 * Кнопками поверх поля с датой, а не вместо него. Час и три часа покрывают
 * почти всё, и набирать ради них дату мышью — четыре нажатия вместо одного;
 * а срок «к четвергу» кнопкой не выразить, и поле остаётся.
 */
const SPANS: { hours: number; title: string }[] = [
  { hours: 0.5, title: "30 мин" },
  { hours: 1, title: "1 час" },
  { hours: 3, title: "3 часа" },
  { hours: 24, title: "Сутки" },
];

/** Что предлагается, пока не выбрали другое. Три часа — работа на полсмены. */
const DEFAULT_HOURS = 3;

export function NewTask({
  card,
  people,
  onClose,
}: {
  card: Card;
  people: Person[];
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const first = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [where, setWhere] = useState<Department>("analysis");
  const [due, setDue] = useState(() => later(DEFAULT_HOURS));
  // Что выбрано кнопкой. Сверять сам срок с «часом от сейчас» нельзя: «сейчас»
  // сдвигается на секунду, и подсветка гасла сама собой через минуту.
  const [pick, setPick] = useState<number | null>(DEFAULT_HOURS);
  const [who, setWho] = useState("");
  const [trouble, setTrouble] = useState("");

  // Escape закрывает: окно открывают из колонки мимоходом, и тянуться мышью к
  // крестику ради отказа от задачи — лишнее движение.
  useEffect(() => {
    first.current?.focus();
    const press = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [onClose]);

  const add = useMutation({
    mutationFn: () =>
      cardsApi.addTask(card.id, {
        title: title.trim(),
        body: body.trim(),
        department: where,
        assignee_id: who || null,
        // Местное время браузера и есть время отдела: платформой пользуются в
        // одном поясе, и «до 16:00» значит одно и то же у всех.
        due_at: due ? new Date(due).toISOString() : null,
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["card-tasks", card.id] });
      void cache.invalidateQueries({ queryKey: ["card-tasks", "open"] });
      void cache.invalidateQueries({ queryKey: ["card", card.id] });
      onClose();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не завелась"),
  });

  const ready = title.trim() !== "" && due !== "";
  const stage = STAGES.some((item) => item.key === where);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-ink/40 px-4 py-4"
      role="dialog"
      aria-modal="true"
      aria-label="Новая задача"
      onMouseDown={(event) =>
        event.target === event.currentTarget && onClose()
      }
    >
      <div className="max-h-[92vh] w-full max-w-[470px] overflow-auto rounded-[14px] border border-hairline bg-surface shadow-[0_18px_48px_rgba(14,22,32,.24)]">
        <header className="flex items-center justify-between gap-3 px-[18px] pt-[15px]">
          <h2 className="text-[15.5px] font-semibold tracking-[-0.015em] text-ink">
            Новая задача
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
          <Field label="Что сделать" id="task-title">
            <input
              id="task-title"
              ref={first}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Согласовать спецификацию"
              className={INPUT}
            />
          </Field>

          <Field label="Описание" id="task-body">
            <textarea
              id="task-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={4}
              placeholder="Что именно проверить, на что смотреть, что вернуть в ответе."
              className={cx(INPUT, "min-h-24 resize-y leading-relaxed")}
            />
          </Field>

          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Куда" id="task-where">
              <select
                id="task-where"
                value={where}
                onChange={(event) => {
                  setWhere(event.target.value as Department);
                  // Исполнитель сбрасывается вместе с отделом: назначенный
                  // юрист в очереди снабжения — задача, которую не сделает
                  // никто.
                  setWho("");
                }}
                className={cx(INPUT, "h-9 py-0")}
              >
                <optgroup label="Этапы лота">
                  {STAGES.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.title}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Отделы">
                  {DESKS.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.title}
                    </option>
                  ))}
                </optgroup>
              </select>
            </Field>

            <Field label="Сколько времени даётся" id="task-due">
              <input
                id="task-due"
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
          </div>

          <Field label="Исполнитель" id="task-who">
            <select
              id="task-who"
              value={who}
              onChange={(event) => setWho(event.target.value)}
              className={cx(INPUT, "h-9 py-0")}
            >
              <option value="">
                {stage ? "Любой — кто возьмёт" : "Любой в отделе — кто возьмёт"}
              </option>
              {people.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name}
                </option>
              ))}
            </select>
          </Field>

          {trouble && <p className="text-[12.5px] text-critical">{trouble}</p>}
        </div>

        <footer className="flex justify-end gap-2 px-[18px] pt-3.5 pb-4">
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            disabled={!ready || add.isPending}
            onClick={() => add.mutate()}
            title={ready ? undefined : "Нужны название и срок"}
          >
            {add.isPending ? "Заводим…" : "Поставить задачу"}
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
  const at = new Date(Date.now() + hours * 60 * 60 * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
}
