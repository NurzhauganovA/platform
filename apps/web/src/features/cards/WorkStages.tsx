/**
 * Второй ряд отбора: где сейчас мяч.
 *
 * «В работе» держит сразу четыре отдела, и внутри одного слова прячется вся
 * работа компании: обсуждение пишут, разбор считает, снабжение ищет товар,
 * юристы отправляют письмо. На планёрке спрашивают не «сколько в работе», а
 * «где какой застрял», и до сих пор ответом было открывание лотов по одному.
 *
 * Лот попадает ровно в одну кнопку — считает сервер лестницей. У кнопки справа
 * значок фильтра: он раскрывает подпункты, и их можно выбрать несколько.
 *
 * **У подпункта есть область, и её тоже объявляет сервер.** «Не написано» и
 * «в процессе» делят свою кнопку; «письмо отправлено», «удовлетворили»,
 * «отклонили» и «не требуется» ищут по всему списку «В работе» — отправленное
 * письмо чаще всего лежит на лоте, который стоит уже в разборе, и под своей
 * кнопкой такой подпункт показывал бы ноль на любых данных.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cardsApi, type Card, type Group, type Choice } from "@/api/cards";
import { cx } from "@/ui";

/** Что выбрано: кнопка верхнего ряда и её подпункты. */
export type Picked = { stage: string; subs: string[] };

export const NOTHING: Picked = { stage: "", subs: [] };

/**
 * Подходит ли лот под отбор.
 *
 * Подпункты **заменяют** условие кнопки объединением, а не сужают его.
 * Пересечение дало бы «В обсуждении 0 → письмо отправлено 0» на любом наборе
 * данных: сквозные подпункты по определению описывают лоты из других кнопок.
 */
export function matches(card: Card, picked: Picked, groups: Group[]): boolean {
  if (!picked.stage) return true;
  const group = groups.find((one) => one.key === picked.stage);
  const chosen =
    group?.subs.filter((sub) => picked.subs.includes(sub.key)) ?? [];
  if (!chosen.length) return card.stage === picked.stage;
  return chosen.some((sub) => fits(card, sub, picked.stage));
}

function fits(card: Card, sub: Choice, stage: string): boolean {
  const keys = sub.of.length ? sub.of : [sub.key];
  const value = String(card[sub.field] ?? "");
  const hit = keys.includes(value);
  return sub.scope === "all" ? hit : hit && card.stage === stage;
}

/** Сколько лотов под подпунктом — по той же формуле, что и отбор. */
function tally(cards: Card[], sub: Choice, stage: string): number {
  return cards.filter((card) => fits(card, sub, stage)).length;
}

export function WorkStages({
  cards,
  picked,
  onChange,
}: {
  /** Лоты «в работе» целиком. Числа считаются от нефильтрованного набора:
   *  число на кнопке должно говорить, сколько там, а не сколько осталось
   *  после уже выбранного. */
  cards: Card[];
  picked: Picked;
  onChange: (next: Picked) => void;
}) {
  const { data: stages } = useQuery({
    queryKey: ["card-stages"],
    queryFn: cardsApi.stages,
    staleTime: Infinity,
  });
  // Какой фильтр раскрыт. Один за раз: два списка рядом перекрывают друг
  // друга, и попасть мышью в нужный становится делом удачи.
  const [opened, setOpened] = useState("");

  if (!stages) return null;

  return (
    <div className="mb-3 rounded-[10px] border border-hairline bg-plane/40 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11.5px] text-ink-muted">Где сейчас</span>
        {stages.work.map((group) => (
          <Chip
            key={group.key}
            group={group}
            cards={cards}
            picked={picked}
            open={opened === group.key}
            onPick={() =>
              onChange(
                picked.stage === group.key
                  ? NOTHING
                  : { stage: group.key, subs: [] },
              )
            }
            onOpen={() => setOpened(opened === group.key ? "" : group.key)}
            onSubs={(subs) => onChange({ stage: group.key, subs })}
            onClose={() => setOpened("")}
          />
        ))}
        {picked.stage && (
          <button
            type="button"
            onClick={() => {
              onChange(NOTHING);
              setOpened("");
            }}
            className="ml-1 text-[11.5px] text-series-1 hover:underline"
          >
            Показать все
          </button>
        )}
      </div>
    </div>
  );
}

function Chip({
  group,
  cards,
  picked,
  open,
  onPick,
  onOpen,
  onSubs,
  onClose,
}: {
  group: Group;
  cards: Card[];
  picked: Picked;
  open: boolean;
  onPick: () => void;
  onOpen: () => void;
  onSubs: (subs: string[]) => void;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const on = picked.stage === group.key;
  const chosen = on ? picked.subs : [];
  const count = cards.filter((card) => card.stage === group.key).length;

  // Escape закрывает список, щелчок мимо — тоже: раскрытый фильтр поверх
  // таблицы иначе остаётся висеть и закрывает собой строки.
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("keydown", key);
    window.addEventListener("mousedown", away);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("mousedown", away);
    };
  }, [open, onClose]);

  return (
    <div ref={box} className="relative">
      <span
        className={cx(
          "flex h-[26px] items-center rounded-[7px] border text-[12px] transition",
          on
            ? "border-ink bg-ink text-surface"
            : "border-hairline text-ink-secondary",
        )}
      >
        <button
          type="button"
          onClick={onPick}
          aria-pressed={on}
          title={group.hint}
          className={cx(
            "flex h-full items-center gap-1.5 rounded-l-[7px] px-2.5",
            !on && "hover:bg-surface",
          )}
        >
          {group.title}
          <span className="tabular-nums opacity-70">{count}</span>
        </button>

        {group.subs.length > 0 && (
          <button
            type="button"
            onClick={onOpen}
            aria-expanded={open}
            aria-label={`Подстатусы: ${group.title}`}
            title="Выбрать подстатусы"
            className={cx(
              "flex h-full items-center rounded-r-[7px] border-l px-1.5",
              on
                ? "border-surface/30 hover:bg-surface/15"
                : "border-hairline hover:bg-surface",
            )}
          >
            <Funnel />
            {/* Сколько подпунктов выбрано — числом на самом значке: иначе
                человек видит суженный список и не понимает, чем он сужен. */}
            {chosen.length > 0 && (
              <span className="ml-1 text-[10.5px] tabular-nums">
                {chosen.length}
              </span>
            )}
          </button>
        )}
      </span>

      {open && (
        <div
          className={cx(
            "absolute top-full left-0 z-20 mt-1 w-[16.5rem] rounded-[10px]",
            "border border-hairline bg-surface p-1.5 shadow-lg",
          )}
        >
          {group.subs.map((sub, index) => (
            <Sub
              key={sub.key}
              sub={sub}
              count={tally(cards, sub, group.key)}
              on={chosen.includes(sub.key)}
              // Черта перед первым сквозным: дальше идут подпункты, которые
              // ищут по всему списку, и число под ними больше, чем на кнопке.
              rule={
                sub.scope === "all" && group.subs[index - 1]?.scope === "in"
              }
              onToggle={() =>
                onSubs(
                  chosen.includes(sub.key)
                    ? chosen.filter((key) => key !== sub.key)
                    : [...chosen, sub.key],
                )
              }
            />
          ))}
          {chosen.length > 0 && (
            <button
              type="button"
              onClick={() => onSubs([])}
              className="mt-1 w-full rounded-[7px] px-2 py-1 text-left text-[11.5px] text-series-1 hover:bg-plane"
            >
              Снять подстатусы
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Sub({
  sub,
  count,
  on,
  rule,
  onToggle,
}: {
  sub: Choice;
  count: number;
  on: boolean;
  rule: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      {rule && (
        <div className="mt-1 mb-1 border-t border-hairline px-2 pt-1.5 text-[10.5px] text-ink-muted">
          по всему списку «В работе»
        </div>
      )}
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={on}
        title={sub.hint}
        className={cx(
          "flex w-full items-center gap-2 rounded-[7px] px-2 py-1.5 text-left text-[12px]",
          "transition hover:bg-plane",
          on ? "text-ink" : "text-ink-secondary",
        )}
      >
        <span
          aria-hidden
          className={cx(
            "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[4px] border",
            on ? "border-series-1 bg-series-1 text-surface" : "border-baseline",
          )}
        >
          {on && (
            <svg
              width="9"
              height="9"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden
            >
              <path
                d="M2.5 6.5 5 9l4.5-5"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </span>
        <span className="min-w-0 flex-1 truncate">{sub.title}</span>
        <span className="shrink-0 text-[11px] text-ink-muted tabular-nums">
          {count}
        </span>
      </button>
    </>
  );
}

/** Воронка — значок фильтра. Свой, а не из набора: в проекте значки рисуются
 *  тут же, и тянуть ради одного целую библиотеку незачем. */
function Funnel() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden>
      <path
        d="M1.5 2h9L7 6.2V10L5 9V6.2L1.5 2Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}
