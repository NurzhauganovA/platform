/**
 * Упоминания в переписке: «@» зовёт коллегу, «@all» — всех.
 *
 * Реплика «посмотри пункт 4.2» без упоминания — это надежда, что человек
 * зайдёт в ветку сам. Заходят в неё тогда, когда о ней напомнили, поэтому
 * упоминание не красит слово, а ставит уведомление.
 *
 * **Кого позвали, считается по тексту, а не по нажатиям.** Список выбора —
 * удобство: имя можно набрать руками, вставить из соседней реплики или
 * дописать при правке, и во всех трёх случаях человека должно позвать. Поэтому
 * перед отправкой текст сверяется с составом организации, а не с тем, что было
 * выбрано мышью.
 *
 * **Собачка внутри слова упоминанием не считается.** В переписке пишут почту
 * поставщика, и «счёт с sales@acme.kz» звал бы список сотрудников на каждую
 * букву после собачки.
 *
 * Однофамильцев зовёт обоих. Разделить их по одному имени в тексте нельзя, а
 * позвать не того хуже, чем позвать лишнего: второй просто закроет уведомление.
 */

import { useMemo, useRef, useState, type ReactNode } from "react";
import type { Person } from "@/api/cards";
import { cx } from "@/ui";
import { ROLE_NAMES } from "./kit";

/** Кого зовёт «@all». То же слово, что на сервере (`discussion.EVERYONE`). */
export const EVERYONE = "all";

/** Слова, которыми зовут всех. Русское рядом с английским: пишут и так и так,
 *  а объяснять человеку разницу не за что. */
const EVERYONE_WORDS = [EVERYONE, "все"];

/** Сколько строк показывать в списке. Больше — это уже поиск по справочнику,
 *  а не подсказка: с двадцатью именами быстрее дописать фамилию руками. */
const SHOWN = 7;

/** Насколько далеко от собачки ещё ищем имя. Длиннее — человек уже не
 *  упоминание пишет, а адрес почты или цену за штуку. */
const TAIL = 24;

type Choice = { key: string; label: string; title: string; hint: string };

/**
 * Кого зовёт эта реплика — по её тексту.
 *
 * Возвращает то, что уходит на сервер: идентификаторы сотрудников и `all`.
 * Сервер сверяет их со своим составом заново — браузеру в таком вопросе не
 * верят, — но собрать список должен тот, кто видит текст.
 */
export function collect(body: string, people: Person[]): string[] {
  const found = new Set<string>();
  const text = body.toLowerCase();

  for (const person of people) {
    const name = person.name.trim().toLowerCase();
    if (name && at(text, `@${name}`)) found.add(person.id);
  }
  for (const word of EVERYONE_WORDS) {
    if (at(text, `@${word}`)) found.add(EVERYONE);
  }
  return [...found];
}

/**
 * Есть ли в тексте это упоминание.
 *
 * Проверяется и то, что стоит перед собачкой: внутри слова она часть почты, а
 * не обращение. Что стоит после имени — не проверяется: за ним идёт запятая,
 * двоеточие или конец строки, и требовать пробела значило бы не звать того, к
 * кому обратились «@Айша, посмотрите».
 */
function at(text: string, needle: string): boolean {
  let from = 0;
  for (;;) {
    const found = text.indexOf(needle, from);
    if (found < 0) return false;
    const before = found === 0 ? " " : text[found - 1];
    if (/[\s(,;:«"']/.test(before)) return true;
    from = found + 1;
  }
}

/**
 * Текст реплики с подсвеченными упоминаниями.
 *
 * Подсветка идёт по составу организации, а не по списку из самой реплики:
 * человек, которого позвали и который потом уволился, должен остаться видимым
 * в переписке — разговор велся с ним.
 */
export function Highlighted({
  body,
  people,
}: {
  body: string;
  people: Person[];
}) {
  const labels = useMemo(
    () =>
      [...people.map((one) => one.name.trim()).filter(Boolean), ...EVERYONE_WORDS]
        // Длинные вперёд: иначе «@Айша» подсветится внутри «@Айша Тлеубаева»
        // и оставит фамилию простым текстом.
        .sort((a, b) => b.length - a.length),
    [people],
  );

  const parts: ReactNode[] = [];
  let from = 0;
  let key = 0;

  outer: while (from < body.length) {
    const found = body.indexOf("@", from);
    if (found < 0) break;
    const before = found === 0 ? " " : body[found - 1];
    if (/[\s(,;:«"']/.test(before)) {
      const tail = body.slice(found + 1).toLowerCase();
      for (const label of labels) {
        if (tail.startsWith(label.toLowerCase())) {
          if (found > from) parts.push(body.slice(from, found));
          parts.push(
            <span key={`m${key++}`} className="font-medium text-series-1">
              {body.slice(found, found + 1 + label.length)}
            </span>,
          );
          from = found + 1 + label.length;
          continue outer;
        }
      }
    }
    // Собачка не наша: пропускаем её и ищем следующую.
    parts.push(body.slice(from, found + 1));
    from = found + 1;
  }
  if (from < body.length) parts.push(body.slice(from));

  return <>{parts}</>;
}

/**
 * Поле ввода со списком сотрудников по «@».
 *
 * Список появляется над полем, а не под ним: поле стоит в самом низу панели, и
 * выпадающий вниз список уезжал бы за край экрана.
 *
 * Стрелки водят по списку, Enter выбирает, Escape закрывает. Пока список
 * открыт, Enter не отправляет реплику: человек в этот момент выбирает имя, а
 * отправленное на середине выбора сообщение приходится дописывать вторым.
 */
export function MentionBox({
  value,
  people,
  onChange,
  onSend,
  rows = 3,
  placeholder,
}: {
  value: string;
  people: Person[];
  onChange: (next: string) => void;
  onSend: () => void;
  rows?: number;
  placeholder?: string;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState<{ at: number; text: string } | null>(null);
  const [active, setActive] = useState(0);

  const choices = useMemo(
    () => (query === null ? [] : suggest(query.text, people)),
    [query, people],
  );
  const open = choices.length > 0;

  /** Ищем незаконченное упоминание слева от курсора. */
  function scan(text: string, caret: number) {
    const before = text.slice(0, caret);
    const found = before.lastIndexOf("@");
    if (found < 0) return setQuery(null);

    const prev = found === 0 ? " " : before[found - 1];
    if (!/[\s(,;:«"']/.test(prev)) return setQuery(null);

    const tail = before.slice(found + 1);
    // Пробел разрешён один: имена у нас из двух слов, а на третьем это уже
    // предложение, в котором собачка осталась от прошлой мысли.
    if (tail.length > TAIL || /\n/.test(tail) || (tail.match(/ /g) ?? []).length > 1) {
      return setQuery(null);
    }
    setQuery({ at: found, text: tail });
    setActive(0);
  }

  function choose(choice: Choice) {
    const node = box.current;
    if (!node || query === null) return;
    const head = value.slice(0, query.at);
    const tail = value.slice(node.selectionStart);
    const next = `${head}@${choice.label} ${tail}`;
    onChange(next);
    setQuery(null);
    // Курсор ставим за вставленным именем: человек продолжает писать реплику, а
    // не ищет, куда делся ввод.
    const caret = head.length + choice.label.length + 2;
    window.requestAnimationFrame(() => {
      node.focus();
      node.setSelectionRange(caret, caret);
    });
  }

  return (
    <div className="relative">
      {open && (
        <ul
          role="listbox"
          aria-label="Кого позвать"
          className={cx(
            "absolute bottom-full left-0 z-10 mb-1.5 max-h-56 w-full overflow-y-auto",
            "rounded-[10px] border border-hairline bg-surface py-1 shadow-lg",
          )}
        >
          {choices.map((choice, index) => (
            <li key={choice.key}>
              <button
                type="button"
                role="option"
                aria-selected={index === active}
                // Мышью выбираем по нажатию, а не по щелчку: щелчок уводит
                // фокус из поля раньше, чем доходит выбор, и вставлять уже
                // некуда.
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(choice);
                }}
                onMouseEnter={() => setActive(index)}
                className={cx(
                  "flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition",
                  index === active ? "bg-series-1/10" : "hover:bg-plane",
                )}
              >
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                  {choice.title}
                </span>
                <span className="shrink-0 text-[11.5px] text-ink-muted">
                  {choice.hint}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <textarea
        ref={box}
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => {
          onChange(event.target.value);
          scan(event.target.value, event.target.selectionStart);
        }}
        // Курсор двигают и стрелками, и мышью: список должен появляться и
        // тогда, когда человек вернулся к недописанному имени.
        onClick={(event) =>
          scan(value, event.currentTarget.selectionStart ?? value.length)
        }
        onKeyUp={(event) => {
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            scan(value, event.currentTarget.selectionStart ?? value.length);
          }
        }}
        onBlur={() => setQuery(null)}
        onKeyDown={(event) => {
          if (open) {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((was) => (was + 1) % choices.length);
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((was) => (was - 1 + choices.length) % choices.length);
              return;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              choose(choices[active]);
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setQuery(null);
              return;
            }
          }
          // Отправка по Ctrl+Enter, а не по Enter: реплики бывают в три
          // строки, и отправленная на первом переносе — это ещё две следом.
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            onSend();
          }
        }}
        className={cx(
          "w-full resize-none rounded-[10px] border border-baseline bg-surface px-3 py-2.5",
          "text-sm leading-relaxed text-ink placeholder:text-ink-muted",
          "focus:border-series-1 focus:outline-none",
        )}
      />
    </div>
  );
}

/**
 * Кого предложить по набранному после собачки.
 *
 * Совпадение с начала любого слова имени: сотрудников зовут и по фамилии, и по
 * имени, а «Тлеубаева» в справочнике записана первой. Совпадение по середине
 * слова не ищем — на двух буквах оно предлагает половину компании.
 */
function suggest(query: string, people: Person[]): Choice[] {
  const text = query.trim().toLowerCase();

  const found: Choice[] = people
    .filter((person) => {
      if (!text) return true;
      return person.name
        .toLowerCase()
        .split(/\s+/)
        .some((word) => word.startsWith(text));
    })
    .slice(0, SHOWN)
    .map((person) => ({
      key: person.id,
      label: person.name.trim(),
      title: person.name,
      hint: ROLE_NAMES[person.role] || person.role,
    }));

  // «Все» — первой строкой и только когда её и набирают: список сотрудников
  // открывают, чтобы позвать одного, и рассылка на всю компанию не должна
  // стоять под пальцем у того, кто целился в коллегу.
  if (text && EVERYONE_WORDS.some((word) => word.startsWith(text))) {
    found.unshift({
      key: EVERYONE,
      label: EVERYONE,
      title: "Все сотрудники",
      hint: "уведомление придёт каждому",
    });
  }
  return found;
}
