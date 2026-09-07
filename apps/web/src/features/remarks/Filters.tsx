/**
 * Отбор обсуждений.
 *
 * Строкой под вкладками, а не столбцом сбоку. Панель фильтров в четверть
 * экрана постоянно занимает место ради того, чем пользуются раз в день, а
 * список замечаний и без того узкий: в нём шесть колонок, и каждая нужна.
 *
 * Сроки корзинами, а не календарём. Календарь требует двух нажатий и знания,
 * какое сегодня число; вопрос при этом всегда один — что горит сегодня.
 *
 * Пустые поля ничего не сужают, и это видно: у сработавшего отбора стоит
 * счётчик, а рядом кнопка сброса. Скрытый фильтр, о котором забыли, — самая
 * частая причина «а где мой лот».
 */

import type { Filters as Query, Outcome } from "@/api/remarks";
import { cx } from "@/ui";

export type Extra = Pick<
  Query,
  "category" | "enstru_code" | "amount_from" | "amount_to" | "ends" | "outcome"
> & { assignee?: string };

const ENDS: { key: NonNullable<Query["ends"]> | ""; title: string }[] = [
  { key: "", title: "Любой срок" },
  { key: "today", title: "Сегодня" },
  { key: "tomorrow", title: "Завтра" },
  { key: "later", title: "Позже" },
  { key: "none", title: "Без срока" },
];

const OUTCOMES: { key: Outcome | ""; title: string }[] = [
  { key: "", title: "Любой итог" },
  { key: "waiting", title: "Ждём ответа" },
  { key: "accepted", title: "Приняли" },
  { key: "rejected", title: "Отклонили" },
  { key: "complaint", title: "Жалоба" },
  { key: "closed", title: "Закрыто" },
];

export function FilterBar({
  value,
  categories,
  onChange,
}: {
  value: Extra;
  categories: string[];
  onChange: (next: Extra) => void;
}) {
  const used = Object.values(value).filter(
    (item) => item !== undefined && item !== "" && item !== null,
  ).length;

  const set = (patch: Partial<Extra>) => onChange({ ...value, ...patch });

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={value.ends ?? ""}
        onChange={(next) => set({ ends: (next || undefined) as Extra["ends"] })}
        options={ENDS.map((item) => [item.key, item.title])}
      />
      <Select
        value={value.outcome ?? ""}
        onChange={(next) => set({ outcome: (next || undefined) as Outcome })}
        options={OUTCOMES.map((item) => [item.key, item.title])}
      />
      <Select
        value={value.category ?? ""}
        onChange={(next) => set({ category: next || undefined })}
        options={[
          ["", "Любая категория"],
          ...categories.map((item) => [item, item] as [string, string]),
        ]}
      />
      <span className="flex items-center gap-1">
        <Money
          value={value.amount_from}
          placeholder="Сумма от"
          onChange={(next) => set({ amount_from: next })}
        />
        <Money
          value={value.amount_to}
          placeholder="до"
          onChange={(next) => set({ amount_to: next })}
        />
      </span>

      <input
        value={value.enstru_code ?? ""}
        onChange={(event) =>
          set({ enstru_code: event.target.value || undefined })
        }
        placeholder="Код ЕНС ТРУ"
        className={cx(
          "h-8 w-40 rounded-[8px] border border-baseline bg-surface px-2.5",
          "font-mono text-xs text-ink placeholder:font-sans placeholder:text-ink-muted",
          "focus:border-series-1 focus:outline-none",
        )}
      />

      {used > 0 && (
        <button
          type="button"
          onClick={() => onChange({})}
          className="h-8 rounded-[8px] px-2.5 text-sm text-ink-secondary transition hover:bg-plane hover:text-ink"
        >
          Сбросить {used}
        </button>
      )}
    </div>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (next: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cx(
        "h-8 max-w-48 rounded-[8px] border bg-surface px-2 text-sm text-ink",
        "focus:border-series-1 focus:outline-none",
        // Сработавший отбор выделен рамкой: иначе о нём забывают, и «а где
        // мой лот» становится ежедневным вопросом.
        value ? "border-series-1" : "border-hairline",
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

function Money({
  value,
  placeholder,
  onChange,
}: {
  value: number | undefined;
  placeholder: string;
  onChange: (next: number | undefined) => void;
}) {
  return (
    <input
      value={value ?? ""}
      inputMode="numeric"
      onChange={(event) => {
        const clean = event.target.value.replace(/[^\d]/g, "");
        onChange(clean ? Number(clean) : undefined);
      }}
      placeholder={placeholder}
      className={cx(
        "h-8 w-24 rounded-[8px] border bg-surface px-2.5",
        "text-sm tabular-nums text-ink placeholder:text-ink-muted",
        "focus:border-series-1 focus:outline-none",
        value === undefined ? "border-hairline" : "border-series-1",
      )}
    />
  );
}
