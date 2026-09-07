/**
 * Полоса хода лота.
 *
 * Одно слово статуса не говорит, сколько ещё идти. Одиннадцать шагов пути
 * подписями в ряд не помещаются и не читаются, поэтому подписан текущий, а
 * остальные показаны отрезками: пройденные залиты, будущие пусты. Взгляд
 * отвечает на «где мы» за долю секунды, а точное название под рукой в
 * подсказке.
 *
 * Сошедший с дистанции лот полосы не получает вовсе. Отменённая заказчиком
 * закупка, показанная на шаге четыре из одиннадцати, читается как «идёт»,
 * хотя не идёт никуда.
 */

import { FLOW, OFF_TRACK, type Card } from "@/api/cards";
import { cx } from "@/ui";

const OFF_WORDS: Record<string, { title: string; why: string }> = {
  skipped: { title: "Не участвуем", why: "Решение наше" },
  lost: { title: "Проиграли", why: "Итоги подведены" },
  cancelled: { title: "Отменён", why: "Заказчик снял закупку" },
};

export function Flow({ card }: { card: Card }) {
  if (OFF_TRACK.includes(card.status)) {
    const words = OFF_WORDS[card.status];
    return (
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-[10px] border border-hairline bg-plane px-4 py-3">
        <span className="text-sm font-semibold text-ink">{words.title}</span>
        <span className="text-sm text-ink-muted">{words.why}</span>
        {card.skip_reason && (
          <span className="w-full text-sm text-ink-secondary">
            {card.skip_reason}
          </span>
        )}
      </div>
    );
  }

  // Шаг приходит с сервера считанным от единицы. Ноль сюда не попадает —
  // его отсеял разбор выше, — но полагаться на это в вычитании не стоит.
  const at = Math.max(card.step, 1);
  const now = FLOW[at - 1];

  return (
    <div className="rounded-[10px] border border-hairline bg-surface px-4 py-3">
      <div className="mb-2.5 flex items-baseline justify-between gap-4">
        <span className="text-sm font-semibold text-ink">
          {now?.title ?? card.status_name}
        </span>
        <span className="text-xs tabular-nums text-ink-muted">
          шаг {at} из {FLOW.length}
        </span>
      </div>
      <ol className="flex gap-1" aria-label="Ход лота">
        {FLOW.map((step, index) => {
          const passed = index < at - 1;
          const here = index === at - 1;
          return (
            <li
              key={step.key}
              title={step.title}
              aria-current={here ? "step" : undefined}
              className={cx(
                "h-1.5 flex-1 rounded-full transition",
                here && "bg-series-1",
                passed && "bg-series-1/35",
                !here && !passed && "bg-hairline",
              )}
            />
          );
        })}
      </ol>
    </div>
  );
}
