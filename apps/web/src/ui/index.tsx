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
  variant?: "primary" | "secondary" | "ghost" | "danger";
  disabled?: boolean;
  className?: string;
};

export function Button({
  children,
  onClick,
  type = "button",
  variant = "secondary",
  disabled,
  className,
}: ButtonProps) {
  const styles = {
    primary: "bg-series-1 text-white hover:opacity-90",
    secondary: "border border-baseline text-ink hover:bg-plane",
    ghost: "text-ink-secondary hover:bg-plane",
    danger: "border border-critical text-critical hover:bg-critical/10",
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
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
      {hint && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
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
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
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
  tone?: "series-1" | "series-2" | "series-3" | "good" | "critical";
}) {
  const accent = tone ? `text-${tone}` : "text-ink";
  return (
    <div className="rounded-[10px] border border-hairline bg-surface px-4 py-3.5">
      <div className="text-xs font-medium text-ink-muted">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className={cx("text-2xl leading-none font-semibold tracking-tight", accent)}>
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
          {count != null && <span className="ml-1.5 font-normal text-ink-muted">{count}</span>}
        </span>
        <span className="flex items-center gap-2">
          {hint && <span className="hidden text-xs text-ink-muted sm:inline">{hint}</span>}
          <span aria-hidden className="text-ink-muted transition group-open:rotate-90">
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
      {description && <p className="max-w-md text-sm text-ink-muted">{description}</p>}
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
export function Progress({ percent, tone = "series-1" }: { percent: number; tone?: string }) {
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
