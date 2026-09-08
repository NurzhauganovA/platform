/**
 * Мелкие детали экрана лота: плашки, отметки, часы, кружки с инициалами.
 *
 * Собраны в одном месте, потому что нужны с обеих сторон экрана. Плашка срока
 * стоит и в рельсе шагов справа, и в шапке обсуждения слева; галочка «сделано»
 * — в рельсе, в списке задач и в полосе подписей. Две копии одной плашки
 * расходятся на первой же правке, и экран начинает выглядеть собранным из
 * двух разных.
 *
 * Плашка своей формы, а не общий `Badge`: тот скруглён кольцом и рассчитан на
 * строку сам по себе, а здесь она встаёт в один ряд с заголовком высотой в
 * двадцать одну точку — кольцо в этом ряду выпирает и ломает базовую линию.
 *
 * Цвет всегда со словом. «Отправлено», «45 мин», «с портала» читаются и без
 * цвета: при дальтонизме красная и оранжевая плашки неразличимы, а это разные
 * дни работы.
 */

import type { ReactNode } from "react";
import { cx } from "@/ui";
import { TZ } from "@/features/worklist/format";

/** Через сколько до срока задача считается горящей. Час: столько занимает
 *  большинство задач целиком, и меньший запас означает «уже не успеть». */
const HOT_MS = 60 * 60 * 1000;

/** А до этого — тёплой. Шесть часов: остаток рабочего дня. */
const WARM_MS = 6 * 60 * 60 * 1000;

/** Насколько срочно. По остатку, а не по признакам сервера: у задач их два —
 *  «взять до» и «сделать до», — а срочность у них считается одинаково. */
export function heat(due: string | undefined): "hot" | "warm" | "calm" {
  if (!due) return "calm";
  const left = new Date(due).getTime() - Date.now();
  if (left < HOT_MS) return "hot";
  if (left < WARM_MS) return "warm";
  return "calm";
}

/** Остаток словами. Коротко: в колонке шириной в триста точек «2 дн. 4 ч.
 *  17 мин.» переносится на вторую строку и ломает ряд. */
export function short(due: string | undefined): string {
  if (!due) return "";
  const left = new Date(due).getTime() - Date.now();
  if (left <= 0) return "просрочена";
  const minutes = Math.floor(left / 60000);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч ${minutes % 60} мин`;
  return `${Math.floor(hours / 24)} д ${hours % 24} ч`;
}

/**
 * Сколько времени дано: от заведения до срока. «3 ч», «45 мин», «2 д».
 *
 * Промежутком, а не двумя датами. «Заведена в 13:00, сделать до 16:00» человек
 * вычитает в уме каждый раз, когда решает, браться ли сейчас, — а решает он
 * это по одному числу.
 */
export function span(from: string, to: string): string {
  const minutes = Math.round(
    (new Date(to).getTime() - new Date(from).getTime()) / 60000,
  );
  if (!Number.isFinite(minutes) || minutes <= 0) return "—";
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ч`;
  return `${Math.round(hours / 24)} д`;
}

/**
 * День и время. Год не пишем: в колонке он занимает место и ничего не даёт.
 *
 * Пояс раздела, а не браузера: сотрудник в командировке смотрит на тот же
 * срок, что и коллеги в офисе, и «до 14:00» должно значить одно и то же.
 */
export function stamp(iso: string): string {
  if (!iso) return "";
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? "—"
    : at.toLocaleString("ru-KZ", {
        timeZone: TZ,
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}

/** Две буквы для кружка. Имя целиком в круг не влезает, а лицо узнают по ним. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts
      .slice(0, 2)
      .map((part) => part[0] ?? "")
      .join("")
      .toUpperCase() || "?"
  );
}

/** Имя коротко: «Анварбек Н.». Полное не влезает в строку рядом со сроком. */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return name;
  return `${parts[0]} ${parts[1][0]}.`;
}

export function Tick({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" aria-hidden>
      <path
        d="M2.6 6.3 4.8 8.5 9.4 3.7"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden
      className={cx(
        "shrink-0 text-ink-muted transition-transform",
        open && "rotate-90",
      )}
    >
      <path
        d="M4.5 2.5 8 6l-3.5 3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className={cx(
        "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
        "bg-series-1/10 text-[9px] font-semibold text-series-1",
      )}
    >
      {initials(name)}
    </span>
  );
}

type Tone = "calm" | "ok" | "hot" | "warm" | "blue";

const TONES: Record<Tone, string> = {
  calm: "bg-plane text-ink-secondary",
  ok: "bg-good/10 text-good",
  hot: "bg-critical/10 text-critical",
  warm: "bg-warning/15 text-ink",
  blue: "bg-series-1/10 text-series-1",
};

/** Плашка в строку заголовка: состояние, срок, откуда пришёл файл. */
export function Chip({
  tone = "calm",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex h-[21px] shrink-0 items-center gap-1 rounded-[5px] px-2",
        "text-[11.5px] font-medium whitespace-nowrap",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

/** Срок плашкой. Цвет со словом: само число «40 мин» не говорит, много это
 *  или мало, пока не знаешь, о чём речь. */
export function Clock({ due }: { due: string }) {
  return (
    <Chip tone={heat(due)} title={`Срок: ${stamp(due)}`}>
      <span className="tabular-nums">{short(due)}</span>
    </Chip>
  );
}

/**
 * Шапка блока: название слева, действия справа, тонкая черта снизу.
 *
 * Одна и та же на всех вкладках. Разъезжалась она молча: у файлов отступ был
 * в шестнадцать точек, у разбора в двадцать, и переключение вкладки сдвигало
 * заголовок на глазах.
 */
export function BarHead({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "flex flex-wrap items-center gap-x-2.5 gap-y-1.5",
        "border-b border-hairline/70 px-[15px] py-[11px]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Название блока. Мельче общего заголовка: блоков на вкладке до трёх, и
 *  крупный шрифт у каждого спорит с названием лота в шапке экрана. */
export function BarTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-[13.5px] font-semibold tracking-[-0.01em] text-ink">
      {children}
    </h3>
  );
}

/** Пояснение мелким рядом с названием или под ним. */
export function Note({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cx("text-[11.5px] text-ink-muted", className)}>
      {children}
    </span>
  );
}
