/**
 * Отбор по сотруднику: список людей с числами и выбор одного.
 *
 * «Мои» отвечает на вопрос от первого лица. Тот же вопрос про соседа —
 * «сколько у него висит и что именно» — задают на планёрке каждый день, и до
 * сих пор ответ на него собирали глазами по колонке «Ведёт». Сотрудников три
 * десятка, лотов сотня: такой подсчёт врёт на второй строке.
 *
 * Числа в самом списке, а не после выбора. Выбирают того, у кого много, а
 * узнать, у кого много, можно только увидев всех сразу; список без чисел
 * заставлял бы перебирать людей по одному.
 *
 * Пустые не прячутся, а уходят вниз и гаснут. «У Иванова ноль» — это ответ, и
 * человек, не нашедший Иванова в списке, идёт проверять, работает ли он ещё
 * у нас.
 *
 * Отбор идёт по уже полученным строкам. Список лежит в памяти вкладки
 * целиком, и запрос на сервер ради того, что можно посчитать на месте, — это
 * полсекунды на каждое нажатие.
 */

import { useEffect, useRef, useState } from "react";
import { cx } from "./index";

/** Один человек в списке: кто и сколько на нём. */
export type Load = {
  id: string;
  name: string;
  /** Строк этого раздела на человеке — лотов, обсуждений. */
  rows: number;
  /** Открытых задач. Не приходит — строка про задачи не рисуется. */
  tasks?: number;
};

export function PeopleFilter({
  people,
  value,
  onChange,
  total,
  unowned,
  word = ["лот", "лота", "лотов"],
  label = "Сотрудник",
}: {
  people: Load[];
  /** Кто выбран. Пусто — все, `none` — ничьи. */
  value: string;
  onChange: (id: string) => void;
  /** Сколько строк всего — для пункта «Все». */
  total: number;
  /**
   * Сколько строк ни на ком. Не задано — строки «Ничьи» нет.
   *
   * Отдельной строкой, а не отсутствием фамилии: ничьё горящее обсуждение и
   * есть то, что теряется, и спрашивают про него чаще, чем про чьё-то.
   */
  unowned?: number;
  /** Слово для числа строк: один, два, пять. */
  word?: [string, string, string];
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  // Закрывается щелчком мимо и по Escape. Список длинный, открывают его на
  // бегу, и оставленный раскрытым он закрывает собой таблицу.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", key);
    };
  }, [open]);

  const picked =
    value === "none"
      ? { name: "Ничьи" }
      : people.find((person) => person.id === value);

  // С нагрузкой вперёд, дальше по алфавиту. Ищут того, у кого много, а не
  // того, чья фамилия ближе к началу.
  const sorted = [...people].sort(
    (a, b) => b.rows - a.rows || a.name.localeCompare(b.name, "ru"),
  );

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        title="Посмотреть лоты одного сотрудника"
        className={cx(
          "flex h-9 items-center gap-2 rounded-[8px] border px-3 text-sm transition",
          "focus-visible:outline focus-visible:outline-2",
          "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
          picked
            ? "border-series-1 bg-series-1/10 text-series-1"
            : "border-baseline text-ink hover:bg-plane",
        )}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M12 12.5a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20c0-3.3 3.4-5 7.5-5s7.5 1.7 7.5 5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
        <span className="max-w-40 truncate">
          {picked ? picked.name : label}
        </span>
        {picked && (
          <span
            role="button"
            tabIndex={0}
            aria-label="Снять отбор"
            onClick={(event) => {
              event.stopPropagation();
              onChange("");
              setOpen(false);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.stopPropagation();
                onChange("");
              }
            }}
            className="-mr-1 rounded px-1 text-xs hover:bg-series-1/20"
          >
            ✕
          </span>
        )}
        <span aria-hidden className="text-[10px] text-ink-muted">
          ▾
        </span>
      </button>

      {open && (
        <div
          className={cx(
            "absolute top-full right-0 z-30 mt-1.5 max-h-96 w-72 overflow-y-auto",
            "rounded-[10px] border border-hairline bg-surface py-1 shadow-xl",
          )}
        >
          <Row
            name="Все сотрудники"
            rows={total}
            word={word}
            chosen={!value}
            onPick={() => {
              onChange("");
              setOpen(false);
            }}
          />
          {unowned !== undefined && (
            <Row
              name="Ничьи"
              rows={unowned}
              word={word}
              chosen={value === "none"}
              onPick={() => {
                onChange("none");
                setOpen(false);
              }}
            />
          )}
          <div className="my-1 border-t border-hairline" />
          {sorted.map((person) => (
            <Row
              key={person.id}
              name={person.name}
              rows={person.rows}
              tasks={person.tasks}
              word={word}
              chosen={person.id === value}
              onPick={() => {
                onChange(person.id);
                setOpen(false);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Row({
  name,
  rows,
  tasks,
  word,
  chosen,
  onPick,
}: {
  name: string;
  rows: number;
  tasks?: number;
  word: [string, string, string];
  chosen: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className={cx(
        "flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition",
        "focus-visible:outline focus-visible:outline-2",
        "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
        chosen ? "bg-series-1/10" : "hover:bg-plane",
      )}
    >
      <span
        className={cx(
          "min-w-0 flex-1 truncate text-sm",
          rows === 0 ? "text-ink-muted" : "text-ink",
          chosen && "font-medium text-series-1",
        )}
      >
        {name}
      </span>
      <span
        className={cx(
          "shrink-0 text-xs whitespace-nowrap tabular-nums",
          rows === 0 ? "text-ink-muted" : "text-ink-secondary",
        )}
      >
        {rows} {plural(rows, word)}
        {/* Задачи вторым числом: лот на человеке и работа по нему — разное.
            Ноль лотов при трёх задачах значит, что он помогает по чужим. */}
        {tasks !== undefined && tasks > 0 && (
          <span className="text-ink-muted"> · {tasks} зад.</span>
        )}
      </span>
    </button>
  );
}

/** Один лот, два лота, пять лотов. */
function plural(count: number, word: [string, string, string]): string {
  const tens = count % 100;
  if (tens > 10 && tens < 20) return word[2];
  const ones = count % 10;
  if (ones === 1) return word[0];
  if (ones >= 2 && ones <= 4) return word[1];
  return word[2];
}
