/**
 * Доска: карточки по колонкам состояния, перетаскивание между ними.
 *
 * Один компонент на «Лоты в работе» и «Обсуждения». Экраны разные по
 * содержимому карточки, но одинаковые по устройству: колонка — состояние,
 * перетаскивание — переход. Две копии этого кода разошлись бы на первой
 * правке, и разошлись бы незаметно — так уже было с полосой вкладок.
 *
 * **Куда можно перетащить, решает сервер.** Список разрешённых состояний
 * приходит вместе с карточкой (`can`), и доска только рисует его. Второй
 * набор правил в браузере однажды разъедется с первым, и человек уронит лот в
 * колонку, получив отказ, — уже будучи уверенным, что перевёл.
 *
 * Перетаскивание — родное, браузерное (`draggable`). Библиотека ради него дала
 * бы плавную анимацию и триста килобайт сверху; здесь этого не нужно —
 * платформа открыта на рабочих машинах с мышью, а карточку тащат на два
 * сантиметра вбок.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "@/ui";

/** Разгон у края: у самой границы быстро, на подходе к ней — едва заметно. */
function ease(part: number): number {
  return part * part;
}

/** Колонка доски: состояние, в котором стоят карточки. */
export type BoardColumn<K extends string> = {
  key: K;
  title: string;
  /** Полоса цвета сверху. Показывает место в пути, а не важность. */
  rule?: string;
  /** Отделить чертой слева: дальше идут состояния вне основного пути. */
  apart?: boolean;
};

export function Board<K extends string, T>({
  columns,
  items,
  columnOf,
  idOf,
  targets,
  onMove,
  card,
  onOpen,
  openId,
  empty,
}: {
  columns: BoardColumn<K>[];
  items: T[];
  /** В какой колонке стоит карточка. */
  columnOf: (item: T) => K;
  idOf: (item: T) => string;
  /** Куда её разрешено перенести. Приходит с сервера, не считается здесь. */
  targets: (item: T) => readonly string[];
  onMove: (item: T, to: K) => void;
  card: (item: T) => ReactNode;
  onOpen: (item: T) => void;
  openId?: string;
  /** Что написать в пустой колонке. Коротко: их на доске большинство. */
  empty?: string;
}) {
  const [dragged, setDragged] = useState<string | null>(null);
  const [over, setOver] = useState<K | null>(null);

  // Открываемся там, где есть работа.
  //
  // Колонок четырнадцать, на экран влезает пять. Первые из них обычно пусты —
  // путь длинный, и лоты стоят в середине или в конце. Доска, открытая на
  // начале, показывает четыре пустые колонки при непустом счётчике во
  // вкладке, и это читается как поломка, а не как «прокрутите вбок».
  const strip = useRef<HTMLDivElement>(null);
  const scrolled = useRef(false);

  /**
   * Прокрутка вбок, когда карточку подносят к краю.
   *
   * Колонок четырнадцать, на экран влезает пять. Без этого «Завершён» не
   * достижим вовсе: колёсиком во время перетаскивания не покрутишь, а
   * отпустить карточку, прокрутить и взять заново — это три действия там, где
   * человек ожидает одно.
   *
   * Скорость растёт по мере приближения к краю, а не включается ступенькой:
   * постоянная скорость либо ползёт, либо проскакивает нужную колонку.
   * Считается кадрами, а не таймером — таймер на шестидесяти герцах даёт
   * рывки, заметные именно на медленном подведении.
   */
  const speed = useRef(0);
  const frame = useRef<number | null>(null);

  const glide = () => {
    const box = strip.current;
    if (!box || speed.current === 0) {
      frame.current = null;
      return;
    }
    box.scrollLeft += speed.current;
    frame.current = requestAnimationFrame(glide);
  };

  const nearEdge = (clientX: number) => {
    const box = strip.current;
    if (!box) return;
    const bounds = box.getBoundingClientRect();
    // Полоса подхвата шире карточки: подносят её неточно, и узкая зона
    // означает, что прокрутка то включается, то гаснет.
    const ZONE = 110;
    const FASTEST = 22;
    const fromLeft = clientX - bounds.left;
    const fromRight = bounds.right - clientX;

    let next = 0;
    if (fromLeft < ZONE) next = -ease(1 - fromLeft / ZONE) * FASTEST;
    else if (fromRight < ZONE) next = ease(1 - fromRight / ZONE) * FASTEST;

    speed.current = next;
    if (next !== 0 && frame.current === null) {
      frame.current = requestAnimationFrame(glide);
    }
  };

  // Кадры отменяются при уходе со страницы: брошенный цикл продолжает
  // крутить доску и после того, как её убрали с экрана.
  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    },
    [],
  );
  useEffect(() => {
    if (scrolled.current || !strip.current) return;
    const filled = new Set(items.map((item) => columnOf(item)));
    if (filled.size === 0) return;
    const first = columns.findIndex((column) => filled.has(column.key));
    if (first <= 0) {
      scrolled.current = true;
      return;
    }
    const box = strip.current;
    const column = box.children[first];
    if (column instanceof HTMLElement) {
      // По разнице границ, а не по `offsetLeft`: тот считается от ближайшего
      // позиционированного предка, а он у полосы и у колонки может быть
      // разным — тогда доска уезжает не туда.
      box.scrollLeft +=
        column.getBoundingClientRect().left - box.getBoundingClientRect().left;
    }
    scrolled.current = true;
  }, [items, columns, columnOf]);

  // Перетащили или щёлкнули — решается здесь. Браузер после перетаскивания
  // щелчок обычно не шлёт, но «обычно» на трёх браузерах означает, что на
  // одном из них лот открывается сам собой в момент броска.
  const moved = useRef(false);

  /**
   * Отпустили — забываем, что тащили.
   *
   * Обязательно здесь, а не только в `onDragEnd` карточки. Карточка в момент
   * броска сразу переезжает в новую колонку: список обновляется, не дожидаясь
   * ответа сервера. React при этом размонтирует её со старого места, и
   * `onDragEnd` на исчезнувшем узле уже не приходит — признак остаётся
   * висеть. Карточка стоит в новой колонке приглушённой, будто перевод
   * подвис, хотя он давно прошёл; а следующий щелчок по ней проглатывается
   * как «это было перетаскивание», и панель не открывается.
   */
  const release = () => {
    setDragged(null);
    setOver(null);
    speed.current = 0;
    // Щелчок после броска приходит следующим кадром — до него признак нужен.
    window.setTimeout(() => {
      moved.current = false;
    }, 0);
  };

  /**
   * Конец перетаскивания ловим на окне, а не только на карточке и колонке.
   *
   * Перетаскивание кончается ровно двумя событиями — `drop` или `dragend`, — и
   * оба всплывают до окна. Ловить их у себя ненадёжно: карточка в момент
   * броска переезжает в другую колонку, React размонтирует её узел, и события
   * на нём уже никто не получит. Тогда доска остаётся приглушённой, будто
   * перевод подвис, хотя он давно прошёл.
   */
  useEffect(() => {
    if (dragged === null) return;
    const finish = () => release();
    window.addEventListener("drop", finish);
    window.addEventListener("dragend", finish);
    return () => {
      window.removeEventListener("drop", finish);
      window.removeEventListener("dragend", finish);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragged]);

  const held = dragged ? items.find((item) => idOf(item) === dragged) : null;
  const allowed = (column: K) =>
    held !== null && held !== undefined && targets(held).includes(column);

  return (
    <div
      ref={strip}
      onDragOver={(event) => nearEdge(event.clientX)}
      onDragLeave={(event) => {
        // Событие всплывает и от колонок: переход между ними — это уход с
        // одной и вход в другую. Гасим разгон только при уходе с доски целиком,
        // иначе прокрутка дёргается на каждой границе колонок.
        const to = event.relatedTarget;
        if (to instanceof Node && event.currentTarget.contains(to)) return;
        speed.current = 0;
      }}
      onDrop={() => {
        speed.current = 0;
      }}
      className="flex gap-3 overflow-x-auto pb-2"
    >
      {columns.map((column) => {
        const inside = items.filter((item) => columnOf(item) === column.key);
        const open = allowed(column.key);
        const shut = held != null && !open && columnOf(held) !== column.key;

        return (
          <section
            key={column.key}
            aria-label={column.title}
            onDragOver={(event) => {
              if (!open) return;
              // Без этого браузер считает, что бросать сюда нельзя, и
              // возвращает карточку на место без единого объяснения.
              event.preventDefault();
              setOver(column.key);
            }}
            onDragLeave={() =>
              setOver((now) => (now === column.key ? null : now))
            }
            onDrop={(event) => {
              event.preventDefault();
              const taken = held;
              const allowedHere = open;
              release();
              if (taken && allowedHere) onMove(taken, column.key);
            }}
            className={cx(
              "flex w-64 shrink-0 flex-col rounded-[10px] border transition",
              over === column.key
                ? "border-series-1 bg-series-1/5"
                : "border-hairline bg-plane/60",
              // Недоступные гасим, а не прячем: исчезающие на время
              // перетаскивания колонки заставляют искать, куда всё делось.
              shut && "opacity-40",
              column.apart && "ml-3 border-dashed",
            )}
          >
            <header className="flex items-center gap-2 px-3 pt-3 pb-2">
              {column.rule && (
                <span
                  className={cx("h-2 w-2 shrink-0 rounded-full", column.rule)}
                  aria-hidden
                />
              )}
              <h3 className="truncate text-sm font-medium text-ink">
                {column.title}
              </h3>
              <span className="ml-auto text-xs tabular-nums text-ink-muted">
                {inside.length || ""}
              </span>
            </header>

            <div className="flex min-h-24 flex-col gap-2 px-2 pb-2">
              {inside.length === 0 ? (
                <p
                  className={cx(
                    "px-1 py-3 text-xs transition",
                    over === column.key
                      ? "text-series-1"
                      : held
                        ? "text-ink-muted"
                        : "text-transparent",
                  )}
                >
                  {over === column.key ? "Отпустите здесь" : empty || "Пусто"}
                </p>
              ) : (
                inside.map((item) => {
                  const id = idOf(item);
                  const movable = targets(item).length > 0;
                  return (
                    <article
                      key={id}
                      draggable={movable}
                      aria-grabbed={dragged === id || undefined}
                      onDragStart={(event) => {
                        moved.current = true;
                        setDragged(id);
                        event.dataTransfer.effectAllowed = "move";
                        // Safari не начинает перетаскивание без данных.
                        event.dataTransfer.setData("text/plain", id);
                      }}
                      // Запасной путь: карточку бросили мимо доски. При броске
                      // в колонку это событие до нас не доходит — узел к тому
                      // моменту уже размонтирован.
                      onDragEnd={release}
                      onClick={() => {
                        if (moved.current) return;
                        onOpen(item);
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        onOpen(item);
                      }}
                      tabIndex={0}
                      role="button"
                      className={cx(
                        "rounded-[8px] border bg-surface p-2.5 text-left transition",
                        "hover:border-baseline focus:border-series-1 focus:outline-none",
                        openId === id
                          ? "border-series-1 ring-1 ring-series-1/30"
                          : "border-hairline",
                        movable
                          ? "cursor-grab active:cursor-grabbing"
                          : "cursor-pointer",
                        dragged === id && "opacity-40",
                      )}
                    >
                      {card(item)}
                    </article>
                  );
                })
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/**
 * Боковая панель подробностей.
 *
 * Поверх доски, а не вместо неё: доска и нужна затем, чтобы видеть остальные
 * лоты, пока разбираешься с этим. Уход на отдельную страницу эту связь рвёт, и
 * человек возвращается обратно, каждый раз заново находя место.
 */
export function Peek({
  title,
  subtitle,
  onClose,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <aside
      className="flex w-80 shrink-0 flex-col rounded-[10px] border border-hairline bg-surface"
      aria-label="Подробности"
    >
      <header className="flex items-start gap-3 border-b border-hairline px-4 py-3">
        <div className="min-w-0">
          {/* В две строки: у лотов портала в названии лежит вся техническая
              спецификация, и целиком она уводит панель на три экрана вниз.
              Полностью её видно ниже, отдельным полем. */}
          <h2
            className="line-clamp-2 text-sm font-semibold text-ink"
            title={title}
          >
            {title}
          </h2>
          {subtitle && (
            <p className="mt-0.5 truncate text-xs text-ink-muted">{subtitle}</p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Закрыть подробности"
          className="ml-auto rounded-[6px] px-2 py-1 text-sm text-ink-muted hover:bg-plane hover:text-ink"
        >
          ✕
        </button>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {children}
      </div>
      {footer && (
        <footer className="border-t border-hairline px-4 py-3">{footer}</footer>
      )}
    </aside>
  );
}
