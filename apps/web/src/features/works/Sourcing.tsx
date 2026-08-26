/**
 * «Где купить» — сравнение вариантов, а не их перечень.
 *
 * Прежний вид отвечал на вопрос «что нам предложили»: строки в том порядке, в
 * каком легли, цена за единицу, срок. Но решают здесь не это. Разбор выбирает,
 * какой вариант подтвердить, и выбор стоит денег: разница в сорок тысяч за
 * штуку на ста пяти штуках — это четыре миллиона, которых в колонке «цена» не
 * видно. Снабжение же не выбирает вовсе, оно заполняет — цену, срок, ссылку.
 *
 * Поэтому здесь:
 *
 * * варианты идут от дешёвого к дорогому, подтверждённый сверху;
 * * рядом с ценой за единицу стоит итог за позицию — то число, которым разница
 *   между вариантами и измеряется;
 * * под ценой и сроком — отставание от лучшего: «дороже на 4 200 000»,
 *   «дольше на 31 день». Компромисс виден без арифметики в уме;
 * * разбору видно, что вариант оставляет заработка. Это и есть его вопрос:
 *   не «который дешевле», а «на чём мы заработаем и успеем ли»;
 * * снабжение правит цену и срок прямо в строке. Это вся его работа, и ради
 *   двух чисел открывать форму на восемь полей незачем.
 *
 * Заявка разбора выглядит заданием, а не сломанной записью: у неё заполнено
 * одно название, и это не недоделка, а смысл — остальное выясняет снабжение.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  worksApi,
  type Work,
  type WorkOption,
  type WorkPosition,
} from "@/api/worklist";
import { Button, cx, money } from "@/ui";
import { OptionForm } from "./OptionForm";

/** Чьё это суждение — по нему видно, насколько варианту верить. */
const SOURCES: Record<WorkOption["source"], { label: string; tone: string }> = {
  found: { label: "нашла модель", tone: "text-ink-muted" },
  asked: { label: "заявка разбора", tone: "text-warning" },
  supply: { label: "нашло снабжение", tone: "text-good" },
};

export function Sourcing({
  work,
  position,
  analysis,
  editable,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  analysis: boolean;
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [asking, setAsking] = useState(false);
  const [editingId, setEditingId] = useState("");

  const editing = position.options.find((option) => option.id === editingId);
  const порядок = ranked(position);
  const дешёвый = best(position, (option) => option.price);
  const быстрый = best(position, (option) => option.delivery_days);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-semibold tracking-wide text-ink">
          ГДЕ КУПИТЬ
          {position.options.length > 1 && (
            <span className="ml-1.5 font-normal text-ink-muted">
              {position.options.length} варианта на выбор
            </span>
          )}
        </h4>
        {editable && (
          <div className="flex items-center gap-1">
            {analysis ? (
              <Button variant="secondary" onClick={() => setAsking(true)}>
                Заказать поиск у снабжения
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => setAdding(true)}>
                + Свой вариант
              </Button>
            )}
          </div>
        )}
      </div>

      {!position.options.length ? (
        <p className="rounded-[8px] border border-dashed border-critical/40 bg-critical/5 px-4 py-3 text-sm text-ink-secondary">
          {analysis
            ? "Ни одного варианта. Подтвердите поставщика или закажите поиск у снабжения — с пустой позицией лот не отправить."
            : "Разбор ничего не приложил. Добавьте то, что найдёте сами."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-[10px] border border-hairline bg-surface">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-hairline bg-plane/60 text-left text-xs text-ink-muted">
                <th className="w-9 px-2 py-2" />
                <th className="px-2 py-2 font-medium">Поставщик</th>
                <th className="w-24 px-2 py-2 font-medium">Страна</th>
                <th className="w-32 px-2 py-2 text-right font-medium">
                  Цена за {position.unit || "ед."}, ₸
                </th>
                <th className="w-36 px-2 py-2 text-right font-medium">
                  Итого за позицию, ₸
                </th>
                <th className="w-28 px-2 py-2 text-right font-medium">Срок</th>
                <th className="w-40 px-2 py-2 text-right font-medium">
                  {analysis ? "Заработок, ₸" : "Чего не хватает"}
                </th>
                <th className="w-24 px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {порядок.map((option) => (
                <Row
                  key={option.id}
                  work={work}
                  position={position}
                  option={option}
                  analysis={analysis}
                  editable={editable}
                  cheapest={дешёвый}
                  fastest={быстрый}
                  onEdit={() => setEditingId(option.id)}
                  onDone={onDone}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <OptionForm
          title="Правка варианта"
          value={editing}
          onSubmit={(fields) =>
            worksApi.editOption(work.id, editing.id, fields)
          }
          onDone={(next) => {
            setEditingId("");
            onDone(next);
          }}
          onCancel={() => setEditingId("")}
        />
      )}
      {adding && (
        <OptionForm
          title="Новый вариант"
          onSubmit={(fields) =>
            worksApi.addOption(work.id, position.id, fields)
          }
          onDone={(next) => {
            setAdding(false);
            onDone(next);
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {asking && (
        <AskForm
          work={work}
          position={position}
          onDone={(next) => {
            setAsking(false);
            onDone(next);
          }}
          onCancel={() => setAsking(false)}
        />
      )}
    </div>
  );
}

function Row({
  work,
  position,
  option,
  analysis,
  editable,
  cheapest,
  fastest,
  onEdit,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  option: WorkOption;
  analysis: boolean;
  editable: boolean;
  cheapest: number | null;
  fastest: number | null;
  onEdit: () => void;
  onDone: (work: Work) => void;
}) {
  const choose = useMutation({
    mutationFn: () => worksApi.choose(work.id, option.id),
    onSuccess: onDone,
  });
  const drop = useMutation({
    mutationFn: () => worksApi.dropOption(work.id, option.id),
    onSuccess: onDone,
  });
  const беда = choose.error ?? drop.error;

  // Заявка разбора: заполнено одно название, остальное выясняет снабжение.
  // Это задание, а не сломанная запись, и выглядеть должно заданием.
  const заявка = option.source === "asked" && option.price === null;
  const количество = position.quantity ?? 1;
  const итого = option.price === null ? null : option.price * количество;
  const заработок =
    analysis && итого !== null && position.total !== null
      ? position.total - итого
      : null;

  return (
    <>
      <tr
        className={cx(
          "border-b border-hairline last:border-0",
          option.chosen && "bg-good/5",
          заявка && "bg-warning/5",
        )}
      >
        <td className="px-2 py-2.5 align-top">
          {option.chosen ? (
            <span
              className="flex size-5 items-center justify-center rounded-full bg-good text-[11px] text-white"
              title="Подтверждён отделом разбора"
            >
              ✓
            </span>
          ) : analysis && editable && !заявка ? (
            <button
              type="button"
              onClick={() => choose.mutate()}
              disabled={choose.isPending}
              title="Подтвердить этого поставщика. Остальные найденные уйдут."
              aria-label="Подтвердить поставщика"
              className="size-5 rounded-full border-2 border-baseline transition hover:border-good hover:bg-good/15"
            />
          ) : (
            <span className="block size-5" />
          )}
        </td>

        <td className="px-2 py-2.5 align-top">
          <div className="font-medium text-ink">
            {option.supplier || (заявка ? "Поставщика ищет снабжение" : "—")}
          </div>
          {option.name && (
            <div className="mt-0.5 break-words text-ink-secondary">
              {option.name}
            </div>
          )}
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
            <span className={SOURCES[option.source].tone}>
              {SOURCES[option.source].label}
            </span>
            {option.url ? (
              <a
                href={option.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-series-1 underline decoration-series-1/30 underline-offset-2"
              >
                {option.marketplace || "товар"} ↗
              </a>
            ) : (
              option.marketplace && (
                <span className="text-ink-muted">{option.marketplace}</span>
              )
            )}
          </div>
          {option.note && (
            <div className="mt-0.5 text-xs text-ink-muted">{option.note}</div>
          )}
        </td>

        <td className="px-2 py-2.5 align-top text-ink-secondary">
          {option.country || "—"}
        </td>

        <td className="px-2 py-2.5 text-right align-top">
          <Amount
            work={work}
            option={option}
            field="price"
            value={option.price}
            editable={editable && !analysis}
            onDone={onDone}
            missing="цену ищут"
          />
          <Delta value={option.price} best={cheapest} suffix="₸" />
        </td>

        <td className="px-2 py-2.5 text-right align-top tabular-nums">
          {итого === null ? (
            <span className="text-ink-muted">—</span>
          ) : (
            <span className="font-medium text-ink">{money(итого)}</span>
          )}
          {итого !== null && cheapest !== null && (
            <Delta value={итого} best={cheapest * количество} suffix="₸" />
          )}
        </td>

        <td className="px-2 py-2.5 text-right align-top">
          <Amount
            work={work}
            option={option}
            field="delivery_days"
            value={option.delivery_days}
            editable={editable && !analysis}
            onDone={onDone}
            missing="срок?"
            unit=" дн."
          />
          <Delta value={option.delivery_days} best={fastest} suffix="дн." />
        </td>

        <td className="px-2 py-2.5 text-right align-top">
          {analysis ? (
            заработок === null ? (
              <span className="text-ink-muted">—</span>
            ) : (
              <span
                className={cx(
                  "font-medium tabular-nums",
                  заработок > 0 ? "text-good" : "text-critical",
                )}
              >
                {заработок > 0 ? "+" : "−"}
                {money(Math.abs(заработок))}
              </span>
            )
          ) : (
            <Gaps option={option} />
          )}
        </td>

        <td className="px-2 py-2.5 align-top">
          {editable && (
            <div className="flex items-center justify-end gap-0.5">
              {!analysis && (
                <button
                  type="button"
                  onClick={onEdit}
                  title="Поставщик, ссылка, страна, примечание"
                  aria-label="Править вариант"
                  className="rounded-[6px] px-1.5 py-1 text-xs text-ink-muted transition hover:bg-plane hover:text-ink"
                >
                  ✎
                </button>
              )}
              {!(заявка && !analysis) && (
                <button
                  type="button"
                  onClick={() => drop.mutate()}
                  disabled={drop.isPending}
                  aria-label="Убрать вариант"
                  title="Убрать вариант"
                  className="rounded-[6px] px-1.5 py-1 text-xs text-ink-muted transition hover:bg-critical/10 hover:text-critical"
                >
                  ✕
                </button>
              )}
            </div>
          )}
        </td>
      </tr>
      {беда && (
        <tr>
          <td colSpan={8} className="px-2 pb-2 text-xs text-critical">
            {беда instanceof Error ? беда.message : "Не получилось"}
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * Число, которое снабжение правит щелчком по нему.
 *
 * Цена и срок — вся работа снабжения по варианту, и открывать ради них форму
 * на восемь полей значит делать в четыре движения то, что делается в одно.
 * Остальные поля правятся формой: их меняют изредка.
 */
function Amount({
  work,
  option,
  field,
  value,
  editable,
  onDone,
  missing,
  unit = "",
}: {
  work: Work;
  option: WorkOption;
  field: "price" | "delivery_days";
  value: number | null;
  editable: boolean;
  onDone: (work: Work) => void;
  missing: string;
  unit?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (next: number) =>
      worksApi.editOption(work.id, option.id, { [field]: next }),
    onSuccess: (work) => {
      setDraft(null);
      onDone(work);
    },
  });

  const принять = () => {
    const число = Number((draft ?? "").replace(",", ".").replace(/\s/g, ""));
    if (!(draft ?? "").trim() || !Number.isFinite(число)) {
      setDraft(null);
      return;
    }
    save.mutate(field === "delivery_days" ? Math.round(число) : число);
  };

  if (draft !== null)
    return (
      <input
        autoFocus
        value={draft}
        inputMode="decimal"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={принять}
        onKeyDown={(event) => {
          if (event.key === "Enter") принять();
          if (event.key === "Escape") setDraft(null);
        }}
        className="w-full rounded-[6px] border border-series-1 bg-surface px-1.5 py-0.5 text-right text-[13px] tabular-nums text-ink focus:outline-none"
      />
    );

  const текст = value === null ? null : `${money(value)}${unit}`;

  if (!editable)
    return текст === null ? (
      <span className="text-warning">{missing}</span>
    ) : (
      <span className="font-medium tabular-nums text-ink">{текст}</span>
    );

  return (
    <button
      type="button"
      onClick={() => setDraft(value === null ? "" : String(value))}
      title="Щёлкните, чтобы изменить"
      className={cx(
        "w-full rounded-[6px] px-1.5 py-0.5 text-right transition",
        "hover:bg-series-1/10 hover:ring-1 hover:ring-series-1/40",
        save.isPending && "opacity-50",
        текст === null ? "text-warning" : "font-medium tabular-nums text-ink",
      )}
    >
      {текст ?? missing}
    </button>
  );
}

/** Отставание от лучшего варианта: компромисс виден без арифметики в уме. */
function Delta({
  value,
  best,
  suffix,
}: {
  value: number | null;
  best: number | null;
  suffix: string;
}) {
  if (value === null || best === null || value <= best) return null;
  return (
    <div className="text-xs tabular-nums text-ink-muted">
      +{money(value - best)} {suffix}
    </div>
  );
}

/**
 * Чего не хватает в варианте — то, что снабжению и предстоит заполнить.
 *
 * Словами, а не цветом: при дальтонизме жёлтая клетка от белой неотличима, а
 * «нет срока» читается одинаково у всех.
 */
function Gaps({ option }: { option: WorkOption }) {
  const дыры = [
    option.price === null && "цена",
    option.delivery_days === null && "срок",
    !option.url && "ссылка",
    !option.supplier && "поставщик",
  ].filter(Boolean) as string[];

  if (!дыры.length)
    return <span className="text-xs font-medium text-good">всё заполнено</span>;
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {дыры.map((дыра) => (
        <span
          key={дыра}
          className="rounded-full bg-warning/15 px-1.5 py-0.5 text-xs text-ink"
        >
          нет: {дыра}
        </span>
      ))}
    </div>
  );
}

/** «Найдите вот это»: заполняется одно название — остальное работа снабжения. */
function AskForm({
  work,
  position,
  onDone,
  onCancel,
}: {
  work: Work;
  position: WorkPosition;
  onDone: (work: Work) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(position.title);
  const ask = useMutation({
    mutationFn: () => worksApi.ask(work.id, position.id, name),
    onSuccess: onDone,
  });

  return (
    <div className="mt-3 rounded-[8px] border border-warning/40 bg-warning/5 px-4 py-3">
      <div className="text-xs font-semibold tracking-wide text-ink">
        ЗАКАЗ ПОИСКА У СНАБЖЕНИЯ
      </div>
      <p className="mt-1 mb-2 text-xs text-ink-secondary">
        Найденное моделью по этой позиции уйдёт: заказ поиска и означает, что
        оно не подходит. Подтверждённый вами поставщик останется.
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Название товара, как его искать"
          className="min-w-0 flex-1 rounded-[8px] border border-baseline bg-surface px-3 py-1.5 text-sm text-ink focus:border-series-1 focus:outline-none"
        />
        <Button
          variant="primary"
          onClick={() => ask.mutate()}
          disabled={ask.isPending || !name.trim()}
        >
          Заказать
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Отмена
        </Button>
      </div>
      {ask.isError && (
        <p className="mt-1.5 text-xs text-critical">
          {ask.error instanceof Error ? ask.error.message : "Не получилось"}
        </p>
      )}
    </div>
  );
}

// --- порядок --------------------------------------------------------------

/**
 * Подтверждённый сверху, дальше от дешёвого к дорогому, без цены — в конец.
 *
 * Порядок, в каком варианты легли в базу, не значит ничего: находки модели
 * приходят как пришли. Сравнивают их по цене, и раскладывать её глазами по
 * четырём строкам человек не должен.
 */
function ranked(position: WorkPosition): WorkOption[] {
  return [...position.options].sort((left, right) => {
    if (left.chosen !== right.chosen) return left.chosen ? -1 : 1;
    if ((left.price === null) !== (right.price === null))
      return left.price === null ? 1 : -1;
    return (left.price ?? 0) - (right.price ?? 0);
  });
}

/** Лучшее значение среди заполненных — то, с чем сравниваются остальные. */
function best(
  position: WorkPosition,
  of: (option: WorkOption) => number | null,
): number | null {
  const known = position.options
    .map(of)
    .filter((value): value is number => value !== null);
  return known.length ? Math.min(...known) : null;
}
