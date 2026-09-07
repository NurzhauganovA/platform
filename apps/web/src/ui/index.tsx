/**
 * Кирпичики интерфейса.
 *
 * Все ссылаются на роли из токенов — `surface`, `ink`, `hairline`, — а не на
 * конкретные цвета. Из-за этого тёмная тема и смена палитры остаются одним
 * местом, а не поиском по файлам.
 */

import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// --- поверхности ----------------------------------------------------------

export function Card({
  children,
  className,
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section
      className={cx(
        "rounded-[10px] border border-hairline bg-surface",
        className,
      )}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-4 border-b border-hairline px-5 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

// --- управление -----------------------------------------------------------

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "secondary" | "accent" | "ghost" | "danger";
  disabled?: boolean;
  className?: string;
  /** Подсказка при наведении. Слово на кнопке короткое по необходимости,
   *  а последствие нажатия объяснить надо — особенно у прерывающих. */
  title?: string;
};

export function Button({
  children,
  onClick,
  type = "button",
  variant = "secondary",
  disabled,
  className,
  title,
}: ButtonProps) {
  const styles = {
    primary: "bg-series-1 text-white hover:opacity-90",
    secondary: "border border-baseline text-ink hover:bg-plane",
    // Второе действие рядом с главным: цвет тот же, заливки нет. Две залитые
    // кнопки подряд спорят за нажатие, а серая рядом с синей читается как
    // отключённая. Слово на кнопке несёт смысл само — цвет только поддержка.
    accent: "border border-series-1 text-series-1 hover:bg-series-1/10",
    ghost: "text-ink-secondary hover:bg-plane",
    danger: "border border-critical text-critical hover:bg-critical/10",
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cx(
        "rounded-[8px] px-3.5 py-2 text-sm font-medium transition",
        "disabled:cursor-not-allowed disabled:opacity-45",
        styles,
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && (
        <span className="mt-1 block text-xs text-ink-muted">{hint}</span>
      )}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "w-full rounded-[8px] border border-baseline bg-surface px-3 py-2 text-sm text-ink",
        "placeholder:text-ink-muted",
        props.className,
      )}
    />
  );
}

// --- состояния ------------------------------------------------------------

type Tone = "neutral" | "good" | "warning" | "serious" | "critical" | "info";

/**
 * Значок состояния.
 *
 * Всегда с текстом, и это не стилистика: цвет состояния сам по себе смысла
 * не несёт — при дальтонизме «в работе» и «ошибка» неразличимы.
 */
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  const styles = {
    neutral: "bg-plane text-ink-secondary border-hairline",
    good: "text-good border-good/40 bg-good/10",
    warning: "text-ink border-warning/50 bg-warning/15",
    serious: "text-ink border-serious/50 bg-serious/15",
    critical: "text-critical border-critical/40 bg-critical/10",
    info: "text-series-1 border-series-1/40 bg-series-1/10",
  }[tone];

  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5",
        "text-xs font-medium whitespace-nowrap",
        styles,
      )}
    >
      {children}
    </span>
  );
}

/**
 * Плитка с числом.
 *
 * Одно значение крупно, подпись рядом. Это форма для «одного показателя»:
 * рисовать столбик из одного столбца — то же число, только дольше читается.
 */
export function StatTile({
  label,
  value,
  unit,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  tone?: "series-1" | "series-2" | "series-3" | "good" | "warning" | "critical";
}) {
  const accent = tone ? `text-${tone}` : "text-ink";
  return (
    <div className="rounded-[10px] border border-hairline bg-surface px-4 py-3.5">
      <div className="text-xs font-medium text-ink-muted">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span
          className={cx(
            "text-2xl leading-none font-semibold tracking-tight",
            accent,
          )}
        >
          {value}
        </span>
        {unit && <span className="text-sm text-ink-secondary">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-xs text-ink-muted">{hint}</div>}
    </div>
  );
}

/**
 * Раздел, свёрнутый по умолчанию.
 *
 * Для того, что нужно изредка и целиком: пятьдесят семь требований
 * технического задания читают один раз при подготовке КП, а на экране они
 * заслоняют то, ради чего человек сюда пришёл, — цены.
 */
export function Collapsible({
  title,
  count,
  hint,
  children,
}: {
  title: string;
  count?: number;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <details className="group rounded-[10px] border border-hairline bg-surface">
      <summary className="flex cursor-pointer items-center justify-between gap-3 px-5 py-3 text-sm">
        <span className="font-semibold text-ink">
          {title}
          {count != null && (
            <span className="ml-1.5 font-normal text-ink-muted">{count}</span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {hint && (
            <span className="hidden text-xs text-ink-muted sm:inline">
              {hint}
            </span>
          )}
          <span
            aria-hidden
            className="text-ink-muted transition group-open:rotate-90"
          >
            ›
          </span>
        </span>
      </summary>
      <div className="border-t border-hairline">{children}</div>
    </details>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && (
        <p className="max-w-md text-sm text-ink-muted">{description}</p>
      )}
      {action}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 text-sm text-ink-secondary">
      <span className="size-3.5 animate-spin rounded-full border-2 border-hairline border-t-series-1" />
      {label}
    </div>
  );
}

/** Полоса выполнения. Проценты подписаны: цвет полосы их не заменяет. */
export function Progress({
  percent,
  tone = "series-1",
}: {
  percent: number;
  tone?: string;
}) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-hairline">
      <div
        className={`h-full rounded-full bg-${tone} transition-[width] duration-300`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  );
}

// --- числа ----------------------------------------------------------------

/** Деньги так, как их пишут в казахстанских документах: 1 234 567,89. */
export function money(value: number, fractionDigits = 0): string {
  return value
    .toLocaleString("ru-KZ", {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    })
    .replace(/ /g, " ");
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} КБ`;
  return `${(value / 1024 / 1024).toFixed(1)} МБ`;
}

// --- строение экрана ------------------------------------------------------

/**
 * Тело страницы под шапкой.
 *
 * Называется `Page`, а не `Screen`: `Screen` — это глобальный тип браузера, и
 * забытый импорт не ломает сборку, а молча подставляет его. Ошибка выглядит
 * как «компонент нельзя использовать в JSX» и ищется долго.
 *
 * Отступы заданы здесь, а не на каждом экране. Разъезжались они молча: на
 * одном `px-8 py-6`, на соседнем `p-6`, и переход между разделами выглядел
 * как переход между двумя разными программами.
 */
export function Page({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cx("space-y-4 px-8 py-6", className)}>{children}</div>;
}

/**
 * Полоса вкладок со счётчиками.
 *
 * Повторялась на пяти экранах слово в слово. Вынесена не ради экономии строк,
 * а потому что каждая копия успела разойтись: где-то счётчик приглушён,
 * где-то нет, где-то другой радиус — и одинаковые по смыслу экраны выглядели
 * сделанными разными людьми.
 */
export function Tabs<T extends string>({
  tabs,
  value,
  counts,
  onChange,
  label = "Отбор",
}: {
  tabs: { key: T; title: string }[];
  value: T;
  /**
   * Счётчики по ключу вкладки. Тип нарочно свободный: `Partial<Record<T, …>>`
   * — недружелюбное для вывода место, из-за него `T` схлопывался до `string`,
   * и `onChange` переставал принимать типизированный обработчик.
   */
  counts?: Record<string, number>;
  /**
   * Обработчик исключён из вывода типа (`NoInfer`).
   *
   * Без этого `setTab` из `useState` ломал вывод: его тип
   * `Dispatch<SetStateAction<Tab>>` даёт кандидата `Tab | ((prev) => Tab)`, а
   * ограничение `T extends string` схлопывает такой союз до `string`. Ошибка
   * читается как «нельзя присвоить обработчик» и указывает не туда: тип
   * вкладок при этом объявлен верно.
   */
  onChange: (next: NoInfer<T>) => void;
  label?: string;
}) {
  return (
    <nav className="flex flex-wrap gap-0.5" aria-label={label}>
      {tabs.map((tab) => {
        const on = tab.key === value;
        const count = counts?.[tab.key] ?? 0;
        return (
          <button
            key={tab.key}
            type="button"
            aria-current={on ? "page" : undefined}
            onClick={() => onChange(tab.key)}
            className={cx(
              "rounded-[8px] px-3 py-1.5 text-sm transition",
              on ? "bg-ink text-surface" : "text-ink-secondary hover:bg-plane",
            )}
          >
            {tab.title}
            {count > 0 && (
              <span
                className={cx(
                  "ml-1.5 tabular-nums",
                  on ? "opacity-70" : "text-ink-muted",
                )}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}

/** Поле поиска. Одна ширина и одна высота на всю платформу. */
export function Search({
  value,
  onChange,
  placeholder = "Поиск",
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <input
      type="search"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className={cx(
        // Рамка `baseline`, а не `hairline`: то же, что у `Input`. Светлая
        // разделительная рамка на поле ввода делает его неотличимым от
        // подложки — человек не понимает, куда щёлкать.
        "h-8 w-56 rounded-[8px] border border-baseline bg-surface px-3",
        "text-sm text-ink placeholder:text-ink-muted",
        "focus:border-series-1 focus:outline-none",
        className,
      )}
    />
  );
}

/**
 * Выпадающий список отбора.
 *
 * Сработавший обведён рамкой цвета ряда. Без этого о включённом фильтре
 * забывают, и «а где мой лот» становится ежедневным вопросом.
 */
export function Choice({
  value,
  onChange,
  options,
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  options: [string, string][];
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cx(
        "h-8 max-w-48 rounded-[8px] border bg-surface px-2 text-sm text-ink",
        "focus:border-series-1 focus:outline-none",
        value ? "border-series-1" : "border-baseline",
        className,
      )}
    >
      {options.map(([key, title]) => (
        <option key={key} value={key}>
          {title}
        </option>
      ))}
    </select>
  );
}

/**
 * Остаток времени словами.
 *
 * Просроченное и горящее выглядят по-разному, а не оттенками одного: по
 * первому делать уже поздно, по второму ещё успеть, и это разные действия.
 * Цифра моноширинная — колонку сроков просматривают сверху вниз.
 */
export function Left({
  text,
  burning,
  overdue,
  strike = "срок прошёл",
}: {
  text: string;
  burning?: boolean;
  overdue?: boolean;
  strike?: string;
}) {
  if (!text) return <span className="text-sm text-ink-muted">—</span>;
  if (overdue) {
    return (
      <span className="text-sm text-ink-muted line-through decoration-baseline">
        {strike}
      </span>
    );
  }
  return (
    <span
      className={cx(
        "text-sm tabular-nums whitespace-nowrap",
        burning ? "font-semibold text-critical" : "text-ink-secondary",
      )}
    >
      {text}
    </span>
  );
}

/** Устойчивый код строки: моноширинный и приглушённый — его читают, не ищут. */
export function Code({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs text-ink-muted">{children}</span>;
}

/**
 * Две строки в одной ячейке: главное и уточнение.
 *
 * Заказчик под названием закупки, лот под задачей. Обе обрезаются по ширине
 * колонки — перенос ломает высоту строки, и таблица перестаёт просматриваться
 * взглядом.
 */
export function Pair({ top, bottom }: { top: ReactNode; bottom?: ReactNode }) {
  return (
    <span className="min-w-0">
      <span className="block truncate text-sm text-ink">{top}</span>
      {bottom ? (
        <span className="mt-0.5 block truncate text-xs text-ink-muted">
          {bottom}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Переключатель из двух-трёх положений.
 *
 * Выбранное отмечено не только цветом: `aria-pressed` читается озвучкой, а
 * фон подкреплён жирностью — при дальтонизме одна заливка неразличима.
 *
 * Жил внутри рабочего списка, пока не понадобился доске. Копия разошлась бы с
 * оригиналом на первой же правке — так уже случилось с полосой вкладок.
 */
export function Switch<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (next: NoInfer<T>) => void;
  options: { value: T; title: string }[];
  label?: string;
}) {
  return (
    <div
      className="flex rounded-[8px] border border-baseline p-0.5"
      role="group"
      aria-label={label}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={cx(
            "rounded-[6px] px-2.5 py-1 text-xs transition",
            value === option.value
              ? "bg-series-1/10 font-semibold text-series-1"
              : "font-medium text-ink-secondary hover:text-ink",
          )}
        >
          {option.title}
        </button>
      ))}
    </div>
  );
}
