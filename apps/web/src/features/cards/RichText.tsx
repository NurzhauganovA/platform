/**
 * Поле с разметкой: ссылки и цвет выделенного.
 *
 * Стоит там, где человек пишет своими словами и по написанному потом работают
 * другие: ячейки разбора и текст замечания заказчику. В обычном поле всё
 * выглядит одинаково — и «не подходит по мощности», и ссылка на страницу
 * товара, и цена, о которой спорили. Выделить это нечем, кроме слов «см. ниже
 * красным», а красного нет.
 *
 * Поэтому две возможности, и ровно те, за которыми приходят: **ссылка** на
 * выделенном тексте и **цвет** выделенного. Жирного и курсива здесь нет
 * намеренно: в ячейку таблицы они не помещаются смыслом — выделять в ней надо
 * не «важное вообще», а «вот это не сходится».
 *
 * Полоса появляется по выделению и рядом с ним, а не висит над полем всегда.
 * Постоянная полоса в таблице на сорок строк — это сорок полос: они съедают
 * высоту, которой и так нет, и мешают читать то, ради чего таблицу открыли.
 *
 * **Разметка ограничена и проверяется на сервере.** Отсюда уходит узкий
 * набор: `<a href>`, `<span style="color">` и перевод строки. Всё остальное —
 * вставленное из Word, из браузера, из письма — вычищается при вставке и ещё
 * раз при сохранении: содержимое чужого документа не должно становиться кодом
 * на нашей странице.
 *
 * Вставка идёт текстом с сохранением ссылок. Word приносит с собой шрифты,
 * размеры и фон таблицы; вставленный как есть, он ломает вид строки и тянет
 * за собой разметку, которую мы всё равно вычистим.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cx } from "@/ui";

/**
 * Цвета для выделения.
 *
 * Роли палитры, а не произвольные: они проверены на контраст и на
 * различимость при дальтонизме. Их пять — больше не нужно: цветом здесь
 * отвечают на «сходится или нет», а это два ответа и три оттенка на оговорки.
 */
const COLORS: { key: string; title: string; css: string }[] = [
  { key: "critical", title: "Не сходится", css: "var(--color-critical)" },
  { key: "good", title: "Подтверждено", css: "var(--color-good)" },
  { key: "warning", title: "Под вопросом", css: "var(--color-warning)" },
  { key: "series-1", title: "Отметить", css: "var(--color-series-1)" },
  { key: "ink", title: "Обычный", css: "var(--color-ink)" },
];

export function RichText({
  value,
  placeholder,
  readOnly = false,
  className,
  onChange,
}: {
  /** Разметка: узкий набор тегов. Пусто — поле пустое. */
  value: string;
  placeholder?: string;
  readOnly?: boolean;
  className?: string;
  onChange: (next: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  /**
   * Выделение на момент нажатия кнопки.
   *
   * Без него ничего не работало. Кнопка забирает фокус, поле выделение теряет,
   * и `createLink` применяется к пустому месту: человек вводил адрес, нажимал
   * «Вставить» и не получал ничего. С полем ввода для адреса это тем более
   * так — пока он там печатает, выделения в тексте уже нет.
   */
  const picked = useRef<Range | null>(null);
  /**
   * Правит ли человек прямо сейчас.
   *
   * Пока правит, разметку в поле не подменяем. Подмена содержимого сбрасывает
   * курсор в начало — а приходит она на каждое нажатие клавиши, потому что
   * сохранение идёт через паузу и возвращает вычищенную разметку. Печатать в
   * таком поле нельзя: курсор прыгает после каждой буквы.
   */
  const typing = useRef(false);

  const [bar, setBar] = useState<{ top: number; left: number } | null>(null);
  const [colors, setColors] = useState(false);
  const [linking, setLinking] = useState(false);
  const [href, setHref] = useState("https://");
  const [trouble, setTrouble] = useState("");
  const [empty, setEmpty] = useState(!plainish(value));

  // Разметка попадает в поле, только когда пришла извне и человек не печатает.
  useLayoutEffect(() => {
    const node = box.current;
    if (!node || typing.current) return;
    if (node.innerHTML !== (value || "")) node.innerHTML = value || "";
    setEmpty(!plainish(node.innerHTML));
  }, [value]);

  // Выделение ловится одним событием на документ, а не нажатиями мыши. Мышью
  // работало, с клавиатуры — нет: у Shift со стрелками последнее нажатие
  // приходит уже без Shift, а «выделить всё» не даёт клавиши вовсе.
  // `selectionchange` — единственный признак, который видит любой способ.
  useEffect(() => {
    const changed = () => {
      // Пока открыт ввод адреса, полосу не трогаем: фокус в поле ввода, и
      // выделения в тексте уже нет — а адрес ещё не введён.
      if (linking) return;
      look();
    };
    document.addEventListener("selectionchange", changed);
    return () => document.removeEventListener("selectionchange", changed);
  }, [linking]);

  useEffect(() => {
    const away = (event: MouseEvent) => {
      const node = box.current;
      const target = event.target as Node;
      if (!node) return;
      if (!node.contains(target) && !inside(target)) hide();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, []);

  function hide() {
    setBar(null);
    setColors(false);
    setLinking(false);
    setTrouble("");
  }

  /** Показывает полосу над выделением — если оно есть и внутри поля. */
  function look() {
    const node = box.current;
    const selection = window.getSelection();
    if (
      readOnly ||
      !node ||
      !selection ||
      selection.isCollapsed ||
      selection.rangeCount === 0
    ) {
      if (!linking) setBar(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!node.contains(range.commonAncestorContainer)) {
      if (!linking) setBar(null);
      return;
    }
    // Запоминаем сразу: дальше человек нажмёт кнопку и выделение исчезнет.
    picked.current = range.cloneRange();
    const spot = range.getBoundingClientRect();
    const own = node.getBoundingClientRect();
    setBar({
      // Относительно поля, а не окна: поле прокручивается вместе с таблицей, и
      // полоса, привязанная к окну, уезжает от своего текста.
      top: spot.top - own.top - 40,
      left: Math.max(0, spot.left - own.left),
    });
  }

  /** Возвращает выделение в поле и применяет команду. */
  function run(apply: () => void): boolean {
    const node = box.current;
    const range = picked.current;
    if (!node || !range) return false;
    // Узлы выделения могли исчезнуть — например, содержимое подменили. Тогда
    // восстанавливать нечего: лучше отказать словами, чем применить команду к
    // пустому месту.
    if (!node.contains(range.commonAncestorContainer)) return false;

    node.focus();
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    if (!selection || selection.isCollapsed) return false;

    apply();
    // Разметку отдаём как есть: чистит её сервер при сохранении, а здесь
    // чистка на каждое нажатие переставляла бы курсор.
    onChange(node.innerHTML);
    setEmpty(!plainish(node.innerHTML));
    picked.current = null;
    return true;
  }

  return (
    <div className="relative">
      <div
        ref={box}
        contentEditable={!readOnly}
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        aria-readonly={readOnly}
        aria-label={placeholder}
        onFocus={() => {
          typing.current = true;
        }}
        onInput={() => {
          const node = box.current;
          if (!node) return;
          setEmpty(!plainish(node.innerHTML));
          onChange(node.innerHTML);
        }}
        onBlur={(event) => {
          const node = box.current;
          if (!node) return;
          // Уход фокуса в полосу — не выход из поля. Это было причиной того,
          // что ссылка вставлялась текстом: чистка подменяла содержимое
          // целиком, запомненное выделение указывало на узлы, которых больше
          // нет, и `createLink` применялся к пустому месту — а браузер на
          // пустом выделении вставляет адрес как текст.
          if (inside(event.relatedTarget as Node | null)) return;

          typing.current = false;
          // Вычищаем на выходе, а не на каждой букве: тут курсора уже нет, и
          // подмена содержимого ничего не сбивает.
          const clean = tidy(node.innerHTML);
          if (clean !== node.innerHTML) node.innerHTML = clean;
          setEmpty(!plainish(clean));
          onChange(clean);
        }}
        onKeyDown={(event) => {
          // Enter — перевод строки, а не новый блок. Браузер по Enter заводит
          // `<div>`, и в ячейке таблицы он даёт отступ на пустую строку.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            document.execCommand("insertLineBreak");
          }
        }}
        onPaste={(event) => {
          event.preventDefault();
          const html = event.clipboardData.getData("text/html");
          const text = event.clipboardData.getData("text/plain");
          // Из разметки оставляем только ссылки и переводы строк: Word и
          // браузер приносят шрифты, размеры и фон таблицы, и вставленные как
          // есть они ломают вид строки.
          insert(html ? tidy(html) : escape(text).replace(/\n/g, "<br>"));
          const node = box.current;
          if (node) {
            setEmpty(!plainish(node.innerHTML));
            onChange(node.innerHTML);
          }
        }}
        data-placeholder={placeholder}
        className={cx(
          "outline-none",
          // Ссылка внутри поля должна выглядеть ссылкой: синей и
          // подчёркнутой. Без этих правил созданный `<a>` ничем не отличался
          // от обычного текста, и человек, поставивший ссылку, видел ровно то
          // же, что и до неё, — то есть считал, что вставилось текстом.
          "[&_a]:cursor-pointer [&_a]:text-series-1 [&_a]:underline [&_a]:decoration-series-1/60",
          // Подсказка рисуется псевдоэлементом: в contentEditable нет
          // `placeholder`, а пустое поле без подсказки читается как сломанное.
          empty &&
            placeholder &&
            "before:pointer-events-none before:text-ink-muted before:content-[attr(data-placeholder)]",
          className,
        )}
      />

      {bar && !readOnly && (
        <div
          data-rich-bar
          style={{ top: bar.top, left: bar.left }}
          className={cx(
            "absolute z-20 flex items-center gap-0.5 rounded-[9px] border border-hairline",
            "bg-surface px-1 py-1 shadow-[0_6px_18px_rgba(14,22,32,.12)]",
          )}
        >
          {linking ? (
            /* Поле ввода здесь же, а не окном браузера. Окно `prompt` забирало
               фокус и рвало выделение — ссылка не ставилась вовсе; к тому же
               оно выглядит чужим и в нём нельзя ни объяснить, чего мы ждём, ни
               показать отказ словами. */
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const clean = href.trim();
                if (!/^https?:\/\//i.test(clean)) {
                  setTrouble("Адрес начинается с http:// или https://");
                  return;
                }
                const ok = run(() =>
                  document.execCommand("createLink", false, clean),
                );
                if (!ok) {
                  // Молчать здесь нельзя: человек ввёл адрес и ждёт ссылку. А
                  // на пустом выделении браузер вставляет адрес текстом —
                  // именно так это и выглядело.
                  setTrouble("Выделение потерялось — выделите текст заново");
                  return;
                }
                setHref("https://");
                hide();
              }}
              className="flex items-center gap-1.5"
            >
              <input
                value={href}
                autoFocus
                onChange={(event) => {
                  setHref(event.target.value);
                  setTrouble("");
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.stopPropagation();
                    setLinking(false);
                  }
                }}
                placeholder="https://"
                aria-label="Адрес ссылки"
                className={cx(
                  "w-56 rounded-[7px] border border-hairline bg-surface px-2 py-1",
                  "text-[12.5px] text-ink placeholder:text-ink-muted",
                  "focus:border-series-1 focus:outline-none",
                )}
              />
              <button
                type="submit"
                className="rounded-[7px] bg-ink px-2.5 py-1 text-[12px] font-medium text-surface"
              >
                Вставить
              </button>
              <button
                type="button"
                onClick={() => setLinking(false)}
                className="rounded-[7px] px-1.5 py-1 text-[12px] text-ink-muted hover:text-ink"
              >
                Отмена
              </button>
              {trouble && (
                <span className="text-[11.5px] text-critical">{trouble}</span>
              )}
            </form>
          ) : (
            <>
              <button
                type="button"
                title="Ссылка на выделенном"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setLinking(true)}
                className="flex h-7 w-7 items-center justify-center rounded-[7px] text-ink-secondary transition hover:bg-plane hover:text-ink"
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M10 13a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 11a4 4 0 0 0-5.66 0l-3 3A4 4 0 0 0 11 19.66l1-1"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                  />
                </svg>
              </button>

              <button
                type="button"
                title="Убрать ссылку"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => run(() => document.execCommand("unlink"))}
                className="flex h-7 w-7 items-center justify-center rounded-[7px] text-ink-secondary transition hover:bg-plane hover:text-ink"
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M9 15l6-6M10 13a4 4 0 0 0 5.66 0l1-1M14 11a4 4 0 0 0-5.66 0l-1 1M4 20L20 4"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                  />
                </svg>
              </button>

              <span aria-hidden className="mx-0.5 h-5 w-px bg-hairline" />

              {/* Круг с градиентом: по нему видно, что за ним цвета, — а не
                  ещё одна буква с непонятным значком. */}
              <button
                type="button"
                title="Цвет выделенного"
                aria-expanded={colors}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setColors((was) => !was)}
                className="flex h-7 w-7 items-center justify-center rounded-[7px] transition hover:bg-plane"
              >
                <span
                  className="h-[15px] w-[15px] rounded-full border border-hairline"
                  style={{
                    background:
                      "conic-gradient(var(--color-critical), var(--color-warning), var(--color-good), var(--color-series-1), var(--color-critical))",
                  }}
                />
              </button>

              {colors &&
                COLORS.map((color) => (
                  <button
                    key={color.key}
                    type="button"
                    title={color.title}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      run(() => {
                        // `styleWithCSS` нужен затем, что без него браузер
                        // пишет устаревший `<font color>`, который мы вычистим
                        // при сохранении — и цвет пропадёт на глазах.
                        document.execCommand("styleWithCSS", false, "true");
                        document.execCommand("foreColor", false, color.css);
                      });
                      hide();
                    }}
                    className="flex h-7 w-7 items-center justify-center rounded-[7px] transition hover:bg-plane"
                  >
                    <span
                      className="h-[15px] w-[15px] rounded-full border border-hairline"
                      style={{ background: color.css }}
                    />
                    <span className="sr-only">{color.title}</span>
                  </button>
                ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Есть ли в поле хоть что-то, кроме разметки. По нему решается подсказка. */
function plainish(html: string): boolean {
  return (
    html
      .replace(/<[^>]*>/g, "")
      .replace(/&nbsp;/g, " ")
      .trim().length > 0
  );
}

/** Полоса и её кнопки — часть поля: ни щелчок по ним, ни уход в них фокуса не
 *  должны считаться выходом из поля. */
function inside(target: Node | null): boolean {
  return Boolean(
    target instanceof Element && target.closest("[data-rich-bar]"),
  );
}

function insert(html: string) {
  document.execCommand("insertHTML", false, html);
}

function escape(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * Оставляет из разметки только разрешённое.
 *
 * Разбор браузером, а не строкой с заменами: строкой это обходится первым же
 * хитро составленным атрибутом, а разбор видит документ так же, как его увидит
 * страница.
 *
 * Тот же список повторяется на сервере при сохранении. Не «на всякий случай»:
 * в базу пишет запрос, а не эта страница, и чистая разметка на экране ничего
 * не говорит о том, что придёт с чужого клиента.
 */
export function tidy(html: string): string {
  const shell = document.createElement("div");
  shell.innerHTML = html;
  clean(shell);
  return shell.innerHTML.trim();
}

const KEEP = new Set(["A", "SPAN", "BR", "DIV", "P"]);

function clean(node: Element) {
  for (const child of Array.from(node.children)) {
    clean(child);

    if (!KEEP.has(child.tagName)) {
      child.replaceWith(...Array.from(child.childNodes));
      continue;
    }

    // Абзацы и блоки превращаются в переводы строки: в ячейке таблицы блочная
    // разметка даёт отступы, которых там быть не должно.
    if (child.tagName === "DIV" || child.tagName === "P") {
      const parts = Array.from(child.childNodes);
      child.replaceWith(...parts, document.createElement("br"));
      continue;
    }

    const color = child.tagName === "SPAN" ? styleColor(child) : "";
    const href =
      child.tagName === "A" ? (child.getAttribute("href") ?? "") : "";
    for (const name of Array.from(child.getAttributeNames())) {
      child.removeAttribute(name);
    }

    if (child.tagName === "A") {
      // Только http и https. `javascript:` в ссылке — это код, исполняемый с
      // нашего адреса по нажатию коллеги.
      if (!/^https?:\/\//i.test(href)) {
        child.replaceWith(...Array.from(child.childNodes));
        continue;
      }
      child.setAttribute("href", href);
      child.setAttribute("target", "_blank");
      child.setAttribute("rel", "noreferrer noopener");
      continue;
    }

    if (color) {
      child.setAttribute("style", `color:${color}`);
    } else {
      child.replaceWith(...Array.from(child.childNodes));
    }
  }
}

/** Цвет из `style`, и только он: остальное оформление не наше дело. */
function styleColor(node: Element): string {
  const style = node.getAttribute("style") ?? "";
  const found = /(?:^|;)\s*color\s*:\s*([^;]+)/i.exec(style);
  if (!found) return "";
  const value = found[1].trim();
  // Значения в кавычках и с функциями не пропускаем: цвет — это или наша
  // переменная палитры, или обычная запись цвета.
  return /^(var\(--color-[a-z0-9-]+\)|#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\))$/i.test(
    value,
  )
    ? value
    : "";
}

/**
 * Показ разметки там, где её не правят: лента, список, письмо.
 *
 * Тот же узкий набор, но без поля ввода. Нужен затем, что разметка лежит в
 * данных, и место, которое покажет её как текст, покажет человеку `<span
 * style="color:red">` словами.
 */
export function Marked({
  html,
  className,
}: {
  html: string;
  className?: string;
}) {
  const safe = tidy(html);
  return (
    <span
      className={cx(
        "[&_a]:text-series-1 [&_a]:underline [&_a]:decoration-series-1/60",
        className,
      )}
      // Разметка вычищена тем же разбором, что и при сохранении: в ней
      // остаются только ссылка и цвет.
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}
