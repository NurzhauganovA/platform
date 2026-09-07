/**
 * Согласование: пять подписей под участием.
 *
 * Строкой, а не столбцом. Вопрос по согласованию всегда один — «кого ждём», —
 * и отвечает на него взгляд слева направо, если подписи стоят в ряд и всегда
 * в одном порядке. Столбец из пяти карточек занимает экран и требует чтения.
 *
 * Своя подпись выделена: у человека здесь одно действие из пяти, и искать
 * его среди чужих он не должен.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { cardsApi, type ApprovalKind, type Card, type Sign } from "@/api/cards";
import { Button, cx } from "@/ui";

const STATE_WORDS: Record<string, string> = {
  waiting: "ждём",
  approved: "согласовал",
  rejected: "против",
};

export function Approvals({
  card,
  onDone,
}: {
  card: Card;
  onDone: (fresh: Card) => void;
}) {
  const [asking, setAsking] = useState<ApprovalKind | null>(null);
  const [why, setWhy] = useState("");

  const put = useMutation({
    mutationFn: (input: { kind: ApprovalKind; ok: boolean; note: string }) =>
      cardsApi.sign(
        card.id,
        input.kind,
        input.ok ? "approved" : "rejected",
        input.note,
      ),
    onSuccess: (fresh) => {
      setAsking(null);
      setWhy("");
      onDone(fresh);
    },
  });

  return (
    <section className="rounded-[10px] border border-hairline bg-surface">
      <header className="flex items-baseline justify-between gap-4 border-b border-hairline px-4 py-2.5">
        <h2 className="text-sm font-semibold text-ink">Согласование</h2>
        <span className="text-xs text-ink-muted">
          {card.approved ? "все подписи собраны" : `${waiting(card)} ждём`}
        </span>
      </header>

      <ul className="grid grid-cols-5 divide-x divide-hairline">
        {card.approvals.map((item) => (
          <Cell
            key={item.kind}
            sign={item}
            busy={put.isPending}
            onYes={() => put.mutate({ kind: item.kind, ok: true, note: "" })}
            onNo={() => setAsking(item.kind)}
          />
        ))}
      </ul>

      {asking && (
        <div className="space-y-2 border-t border-hairline bg-plane px-4 py-3">
          <label className="block text-sm text-ink">
            Что мешает согласовать
            <textarea
              value={why}
              onChange={(event) => setWhy(event.target.value)}
              rows={2}
              autoFocus
              placeholder="Подпись «против» без причины останавливает работу и не говорит, что чинить"
              className={cx(
                "mt-1.5 w-full resize-none rounded-[8px] border border-baseline bg-surface p-2.5",
                "text-sm text-ink placeholder:text-ink-muted",
                "focus:border-series-1 focus:outline-none",
              )}
            />
          </label>
          <div className="flex gap-2">
            <Button
              variant="danger"
              disabled={!why.trim() || put.isPending}
              onClick={() => put.mutate({ kind: asking, ok: false, note: why })}
            >
              Не согласовать
            </Button>
            <Button variant="ghost" onClick={() => setAsking(null)}>
              Отмена
            </Button>
          </div>
        </div>
      )}

      {put.error && (
        <p className="border-t border-hairline px-4 py-2.5 text-sm text-critical">
          {put.error instanceof Error ? put.error.message : "Не получилось"}
        </p>
      )}
    </section>
  );
}

function Cell({
  sign,
  busy,
  onYes,
  onNo,
}: {
  sign: Sign;
  busy: boolean;
  onYes: () => void;
  onNo: () => void;
}) {
  return (
    <li
      className={cx(
        "flex flex-col gap-1.5 px-3 py-3",
        sign.can_sign && sign.state === "waiting" && "bg-series-1/[0.04]",
      )}
    >
      <span className="text-xs font-medium tracking-wide text-ink-muted uppercase">
        {sign.name}
      </span>

      <span
        className={cx(
          "text-sm",
          sign.state === "approved" && "text-good",
          sign.state === "rejected" && "font-medium text-critical",
          sign.state === "waiting" && "text-ink-muted",
        )}
      >
        {STATE_WORDS[sign.state]}
      </span>

      {sign.by && (
        <span className="truncate text-xs text-ink-muted" title={sign.by}>
          {sign.by}
        </span>
      )}
      {sign.note && (
        <span className="text-xs leading-relaxed text-ink-secondary">
          {sign.note}
        </span>
      )}

      {sign.can_sign && sign.state !== "approved" && (
        <div className="mt-auto flex gap-1 pt-1">
          <button
            type="button"
            disabled={busy}
            onClick={onYes}
            className="rounded-[6px] border border-good/50 px-2 py-1 text-xs text-good transition hover:bg-good/10 disabled:opacity-45"
          >
            Согласен
          </button>
          {sign.state !== "rejected" && (
            <button
              type="button"
              disabled={busy}
              onClick={onNo}
              className="rounded-[6px] px-2 py-1 text-xs text-ink-muted transition hover:bg-plane disabled:opacity-45"
            >
              Нет
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function waiting(card: Card): number {
  return card.approvals.filter((item) => item.state === "waiting").length;
}
