/**
 * Все состояния лота в одном окне.
 *
 * Переходы свободные: перевести можно откуда угодно куда угодно. Четырнадцать
 * кнопок в узкой колонке справа стали бы списком настроек, поэтому там
 * остались только ближайшие, а полный набор живёт здесь.
 *
 * Разложено по смыслу и с подписью у каждого: «Ожидаем оплату» и «Ожидаем
 * итоги» различаются одним словом, и без пояснения в них промахиваются.
 * Поиск — потому что четырнадцать это уже больше, чем окидывают взглядом.
 */

import { useEffect, useState } from "react";
import { FLOW, type Card, type LotStatus } from "@/api/cards";
import { Input, cx } from "@/ui";

export const STATUS_NAMES: Record<LotStatus, string> = {
  new: "Новый",
  discussion: "Обсуждение",
  analysis: "На разборе",
  approval: "На согласовании",
  ready: "Готов к участию",
  awaiting: "Ожидаем итоги",
  won: "Выиграли",
  contract: "Договор",
  fulfilling: "Исполнение",
  awaiting_payment: "Ожидаем оплату",
  done: "Завершён",
  skipped: "Не участвуем",
  lost: "Проиграли",
  cancelled: "Отменён",
};

const ABOUT: Record<LotStatus, string> = {
  new: "взяли в работу, ещё не смотрели",
  discussion: "замечание к техспецификации",
  analysis: "себестоимость, товар, решение",
  approval: "собираем пять подписей",
  ready: "подписи собраны, можно подавать",
  awaiting: "заявка подана",
  won: "победили",
  contract: "подписываем договор",
  fulfilling: "везём и поставляем",
  awaiting_payment: "поставили, ждём деньги",
  done: "деньги получены",
  skipped: "решили пропустить",
  lost: "выиграл другой",
  cancelled: "заказчик отменил закупку",
};

const GROUPS: { title: string; keys: LotStatus[] }[] = [
  { title: "Подготовка", keys: ["new", "discussion", "analysis", "approval"] },
  { title: "Участие", keys: ["ready", "awaiting", "won"] },
  {
    title: "Исполнение",
    keys: ["contract", "fulfilling", "awaiting_payment", "done"],
  },
  { title: "Сошли с дистанции", keys: ["skipped", "lost", "cancelled"] },
];

export function StatusModal({
  card,
  onClose,
  onPick,
}: {
  card: Card;
  onClose: () => void;
  onPick: (to: LotStatus) => void;
}) {
  const [needle, setNeedle] = useState("");

  // Esc закрывает: окно поверх работы, и выход из него должен быть там же,
  // где его ищут.
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [onClose]);

  const step = FLOW.findIndex((item) => item.key === card.status);
  const ahead = step >= 0 ? FLOW[step + 1]?.key : undefined;
  const search = needle.trim().toLowerCase();
  const fits = (key: LotStatus) =>
    !search ||
    STATUS_NAMES[key].toLowerCase().includes(search) ||
    ABOUT[key].includes(search);

  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center bg-ink/25 px-6 py-20"
      role="dialog"
      aria-modal="true"
      aria-label="Сменить статус"
      onClick={onClose}
    >
      <div
        className="w-full max-w-4xl overflow-hidden rounded-[12px] border border-hairline bg-surface shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-hairline px-5 py-3">
          <h2 className="text-[15px] font-semibold text-ink">
            Сменить статус · {card.code}
          </h2>
          <p className="text-sm text-ink-muted">
            сейчас {card.status_name} · переходы свободные, из любого состояния
            в любое
          </p>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-sm text-series-1 hover:underline"
          >
            Закрыть
          </button>
        </header>

        <div className="px-5 py-3">
          <Input
            value={needle}
            onChange={(event) => setNeedle(event.target.value)}
            placeholder="Поиск: «догов», «оплат»…"
            className="max-w-sm"
            autoFocus
          />
        </div>

        <div className="grid grid-cols-4 gap-4 px-5 pb-4">
          {GROUPS.map((group) => (
            <div key={group.title}>
              <p className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
                {group.title}
              </p>
              <div className="space-y-2">
                {group.keys.filter(fits).map((key) => (
                  <Choice
                    key={key}
                    status={key}
                    here={key === card.status}
                    ahead={key === ahead}
                    allowed={card.can.includes(key)}
                    card={card}
                    onPick={onPick}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>

        <p className="border-t border-hairline px-5 py-3 text-sm text-ink-muted">
          Остались только два условия, и они про деньги: «Готов к участию» ждёт
          все пять подписей, «Не участвуем» — причину. Условие видно до нажатия,
          а не отказом после.
        </p>
      </div>
    </div>
  );
}

function Choice({
  status,
  here,
  ahead,
  allowed,
  card,
  onPick,
}: {
  status: LotStatus;
  here: boolean;
  ahead: boolean;
  allowed: boolean;
  card: Card;
  onPick: (to: LotStatus) => void;
}) {
  const signed = card.approvals.filter(
    (sign) => sign.state === "approved",
  ).length;
  const why =
    status === "ready" && !allowed && !here
      ? `нужны все пять подписей — сейчас ${signed}`
      : status === "skipped" && allowed
        ? "спросит причину: без неё не переведётся"
        : "";

  return (
    <button
      type="button"
      disabled={here || !allowed}
      onClick={() => onPick(status)}
      className={cx(
        "w-full rounded-[8px] border px-3 py-2 text-left transition",
        here
          ? "border-series-1 bg-series-1/10"
          : ahead && allowed
            ? "border-series-1/50 bg-series-1/5 hover:bg-series-1/10"
            : why && !allowed
              ? "border-warning/40 bg-warning/5"
              : allowed
                ? "border-hairline hover:border-baseline hover:bg-plane"
                : "cursor-not-allowed border-hairline opacity-60",
      )}
    >
      <span className="flex items-baseline gap-2">
        <span className="text-sm font-medium text-ink">
          {STATUS_NAMES[status]}
        </span>
        {here && <span className="ml-auto text-xs text-series-1">сейчас</span>}
        {ahead && !here && (
          <span className="ml-auto text-xs text-series-1">следующий</span>
        )}
        {!here && !ahead && why && !allowed && (
          <span className="ml-auto text-xs text-warning">условие</span>
        )}
      </span>
      <span className="mt-0.5 block text-xs text-ink-muted">
        {here ? "текущее состояние" : ABOUT[status]}
      </span>
      {why && (
        <span
          className={cx(
            "mt-0.5 block text-xs",
            allowed ? "text-ink-muted" : "text-critical",
          )}
        >
          {why}
        </span>
      )}
    </button>
  );
}
