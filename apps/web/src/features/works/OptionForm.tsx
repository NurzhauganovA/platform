/**
 * Вариант закупки: добавить или поправить.
 *
 * Одна форма на оба случая. Поля те же, и разводить их по двум компонентам
 * значит однажды добавить срок поставки в одно место и забыть про второе.
 *
 * Срок поставки стоит рядом с ценой, а не в конце: для снабжения это второе
 * по важности поле после цены — от срока зависит, беремся ли мы вообще, а
 * узнать его до снабжения неоткуда.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import type { OptionFields, Work, WorkOption } from "@/api/worklist";
import { Button, cx } from "@/ui";

type Draft = {
  name: string;
  supplier: string;
  marketplace: string;
  country: string;
  url: string;
  price: string;
  delivery_days: string;
  note: string;
};

const EMPTY: Draft = {
  name: "",
  supplier: "",
  marketplace: "",
  country: "",
  url: "",
  price: "",
  delivery_days: "",
  note: "",
};

export function OptionForm({
  title,
  value,
  onSubmit,
  onDone,
  onCancel,
}: {
  title: string;
  /** Что правим. Пусто — добавляем новый. */
  value?: WorkOption;
  onSubmit: (fields: OptionFields) => Promise<Work>;
  onDone: (work: Work) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() =>
    value
      ? {
          name: value.name,
          supplier: value.supplier,
          marketplace: value.marketplace,
          country: value.country,
          url: value.url,
          price: value.price === null ? "" : String(value.price),
          delivery_days:
            value.delivery_days === null ? "" : String(value.delivery_days),
          note: value.note,
        }
      : EMPTY,
  );

  const save = useMutation({
    mutationFn: () => onSubmit(_fields(draft)),
    onSuccess: onDone,
  });

  const set = (field: keyof Draft) => (event: { target: { value: string } }) =>
    setDraft({ ...draft, [field]: event.target.value });

  return (
    <div className="mt-3 rounded-[8px] border border-series-1/40 bg-plane px-4 py-3">
      <div className="mb-3 text-xs font-medium text-ink-muted">
        {title.toUpperCase()}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Поставщик"
          value={draft.supplier}
          onChange={set("supplier")}
        />
        <Field
          label="Что покупаем"
          value={draft.name}
          onChange={set("name")}
          hint="Как товар назван у поставщика"
        />
        <Field
          label="Цена за единицу, ₸"
          value={draft.price}
          onChange={set("price")}
          numeric
        />
        <Field
          label="Срок поставки, дней"
          value={draft.delivery_days}
          onChange={set("delivery_days")}
          numeric
          hint="Через сколько товар у нас"
        />
        <Field
          label="Площадка"
          value={draft.marketplace}
          onChange={set("marketplace")}
        />
        <Field label="Страна" value={draft.country} onChange={set("country")} />
        <div className="sm:col-span-2">
          <Field
            label="Ссылка на товар"
            value={draft.url}
            onChange={set("url")}
            hint="Именно на товар, а не на раздел площадки"
          />
        </div>
        <div className="sm:col-span-2">
          <Field label="Примечание" value={draft.note} onChange={set("note")} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          onClick={() => save.mutate()}
          disabled={save.isPending}
        >
          {save.isPending ? "Сохраняем…" : "Сохранить"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Отмена
        </Button>
        {save.isError && (
          <span className="text-xs text-critical">
            {save.error instanceof Error
              ? save.error.message
              : "Не сохранилось"}
          </span>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  hint,
  numeric,
}: {
  label: string;
  value: string;
  onChange: (event: { target: { value: string } }) => void;
  hint?: string;
  numeric?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-xs text-ink-muted">{label}</span>
      <input
        value={value}
        onChange={onChange}
        inputMode={numeric ? "decimal" : undefined}
        className={cx(
          "mt-1 w-full rounded-[8px] border border-baseline bg-surface px-3 py-1.5",
          "text-sm text-ink placeholder:text-ink-muted",
          "focus:border-series-1 focus:outline-none",
          numeric && "tabular-nums",
        )}
      />
      {hint && (
        <span className="mt-0.5 block text-xs text-ink-muted">{hint}</span>
      )}
    </label>
  );
}

/**
 * Пустое поле — это «не заполнено», а не «сотри».
 *
 * Правка идёт по одному полю: поправили цену — ссылка не должна обнулиться
 * заодно. Поэтому пустые строки просто не уходят на сервер.
 */
function _fields(draft: Draft): OptionFields {
  const fields: OptionFields = {};
  for (const key of [
    "name",
    "supplier",
    "marketplace",
    "country",
    "url",
    "note",
  ] as const) {
    if (draft[key].trim()) fields[key] = draft[key].trim();
  }
  const цена = Number(draft.price.replace(",", ".").replace(/\s/g, ""));
  if (draft.price.trim() && Number.isFinite(цена)) fields.price = цена;
  const срок = Number(draft.delivery_days.replace(/\s/g, ""));
  if (draft.delivery_days.trim() && Number.isFinite(срок))
    fields.delivery_days = Math.round(срок);
  return fields;
}
