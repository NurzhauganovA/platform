/**
 * Второй ряд отбора — подстатусы «В работе».
 *
 * «В работе» держит сразу четыре отдела, и внутри одного слова прячется вся
 * работа компании: обсуждение пишется, разбор считает, снабжение ищет товар,
 * юристы отправляют письмо. На планёрке спрашивают не «сколько в работе», а
 * «где какой застрял», и до сих пор ответом было открывание лотов по одному.
 *
 * **Два отбора, а не один список.** У лота два независимых ответа: где его
 * обсуждение и где он сам по отделам. Свалить двенадцать кнопок в один ряд
 * значило бы заставить выбирать между «письмо отправлено» и «у снабженцев» —
 * а это один и тот же лот, и оба ответа верны. Поэтому рядов два, и они
 * сужают список вместе.
 *
 * Показывается только на вкладке «В работе». На остальных этапах отделов уже
 * нет: лот на согласовании ждёт подписей, на подаче — заявки.
 */

import { useQuery } from "@tanstack/react-query";
import { cardsApi, type Card, type Pick, type Stages } from "@/api/cards";
import { cx } from "@/ui";

export type Picked = { talk: string; desk: string };

/**
 * Подходит ли лот под выбранный отбор. Пустой выбор ничего не сужает.
 *
 * Состав групп берётся из ответа сервера, а не повторяется здесь списком:
 * «завершённые» — это три исхода письма, и второе такое же определение на
 * другом языке разошлось бы с первым молча.
 */
export function matches(card: Card, picked: Picked, stages?: Stages): boolean {
  return (
    fits(card.talk_stage, picked.talk, stages?.talk) &&
    fits(card.desk_stage, picked.desk, stages?.desk)
  );
}

function fits(value: string, want: string, items?: Pick[]): boolean {
  if (!want) return true;
  const group = items?.find((item) => item.key === want);
  return group?.of.length ? group.of.includes(value) : value === want;
}

export function WorkStages({
  cards,
  picked,
  onChange,
}: {
  /** Лоты «в работе» — по ним считаются числа. Считаем от нефильтрованного
   *  набора: число на кнопке должно говорить, сколько там, а не сколько
   *  осталось после уже выбранного. */
  cards: Card[];
  picked: Picked;
  onChange: (next: Picked) => void;
}) {
  // Набор кнопок один на платформу и меняется правкой кода, а не данными:
  // спрашиваем раз за сессию и держим до перезагрузки вкладки.
  const { data: stages } = useQuery({
    queryKey: ["card-stages"],
    queryFn: cardsApi.stages,
    staleTime: Infinity,
  });
  if (!stages) return null;

  const rows = (items: Pick[], value: string, pick: (key: string) => void) => (
    <Group
      items={items.map((item) => ({
        key: item.key,
        title: item.title,
        hint: item.hint,
        count: tally(cards, item),
        // Кнопка-группа стоит перед своими, а те — со сдвигом: три ответа
        // заказчика читаются как её продолжение, а не как соседи по ряду.
        nested: items.some(
          (other) => other.of.length > 0 && other.of.includes(item.key),
        ),
      }))}
      value={value}
      onPick={pick}
    />
  );

  return (
    <div className="mb-3 flex flex-col gap-2 rounded-[10px] border border-hairline bg-plane/40 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 w-[6.5rem] shrink-0 text-[11.5px] text-ink-muted">
          В обсуждении
        </span>
        {rows(stages.talk, picked.talk, (key) =>
          onChange({ ...picked, talk: key === picked.talk ? "" : key }),
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 w-[6.5rem] shrink-0 text-[11.5px] text-ink-muted">
          В разборе
        </span>
        {rows(stages.desk, picked.desk, (key) =>
          onChange({ ...picked, desk: key === picked.desk ? "" : key }),
        )}
      </div>
      {(picked.talk || picked.desk) && (
        <button
          type="button"
          onClick={() => onChange({ talk: "", desk: "" })}
          className="self-start text-[11.5px] text-series-1 hover:underline"
        >
          Показать все
        </button>
      )}
    </div>
  );
}

/** Сколько лотов под кнопкой. У группы — сумма её подстатусов. */
function tally(cards: Card[], item: Pick): number {
  const keys = item.of.length ? item.of : [item.key];
  return cards.filter(
    (card) => keys.includes(card.talk_stage) || keys.includes(card.desk_stage),
  ).length;
}

type Item = {
  key: string;
  title: string;
  hint: string;
  count: number;
  nested: boolean;
};

function Group({
  items,
  value,
  onPick,
}: {
  items: Item[];
  value: string;
  onPick: (key: string) => void;
}) {
  return (
    <>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => onPick(item.key)}
          aria-pressed={value === item.key}
          title={item.hint}
          className={cx(
            "flex h-[26px] items-center gap-1.5 rounded-[7px] px-2.5 text-[12px] transition",
            // Вложенные — со сдвигом и точкой: три ответа заказчика
            // принадлежат «Завершённым», и ряд из семи равных кнопок эту
            // связь прятал.
            item.nested && "ml-0.5",
            value === item.key
              ? "bg-ink text-surface"
              : item.count === 0
                ? "border border-hairline text-ink-muted"
                : "border border-hairline text-ink-secondary hover:bg-surface",
          )}
        >
          {item.nested && (
            <span aria-hidden className="text-ink-muted">
              ·
            </span>
          )}
          {item.title}
          {/* Число всегда, включая ноль: пустой подстатус — это ответ «таких
              нет», а кнопка без числа выглядит непосчитанной. */}
          <span className="tabular-nums opacity-70">{item.count}</span>
        </button>
      ))}
    </>
  );
}
