/**
 * Согласование: что нужно подписать перед подачей.
 *
 * Экран одного вопроса — «кого ждём и успеваем ли». Поэтому пять подписей
 * стоят колонками таблицы, а не прячутся внутри карточки: строка отвечает
 * взглядом, без открытия лота.
 *
 * Срок здесь свой, короче общего: подписи должны быть собраны за два часа до
 * окончания приёма. Не запас на подпись, а запас на подачу — заявку подают
 * руками, и десять минут до срока означают спешку, в которой прикладывают не
 * тот файл.
 *
 * Своё выделено. У человека на этом экране одно действие из пяти, и искать
 * его среди чужих подписей он не должен.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cardsApi, type ApprovalKind, type Card, type Sign } from "@/api/cards";
import { PageHeader } from "@/shell/AppShell";
import {
  Card as Panel,
  EmptyState,
  Page,
  Spinner,
  Tabs,
  cx,
  money,
} from "@/ui";

const KINDS: ApprovalKind[] = [
  "manager",
  "supply",
  "legal",
  "technologist",
  "assembler",
];

const TITLES: Record<ApprovalKind, string> = {
  manager: "Менеджер",
  supply: "Снабжение",
  legal: "Юрист",
  technologist: "Технолог",
  assembler: "Сборщик",
};

type Tab = "waiting" | "mine" | "rejected" | "ready";

const TABS: { key: Tab; title: string }[] = [
  { key: "mine", title: "Ждут меня" },
  { key: "waiting", title: "Не собраны" },
  { key: "rejected", title: "Есть отказ" },
  { key: "ready", title: "Собраны" },
];

export function ApprovalPage() {
  const [tab, setTab] = useState<Tab>("mine");
  const cache = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["cards"],
    queryFn: () => cardsApi.list(),
    refetchInterval: 60_000,
  });

  // На согласовании — те, кто дошёл до него и ещё не подан. Готовые к участию
  // здесь тоже нужны: подписи собраны, но лот ещё не ушёл, и отказ поступает
  // именно в этот промежуток.
  const all = useMemo(
    () =>
      (data ?? []).filter(
        (item) => item.status === "approval" || item.status === "ready",
      ),
    [data],
  );
  const counts = useMemo(() => countBy(all), [all]);
  const shown = useMemo(
    () => all.filter((item) => belongs(item, tab)),
    [all, tab],
  );

  const refresh = (fresh: Card) =>
    cache.setQueryData<Card[]>(["cards"], (old) =>
      (old ?? []).map((item) => (item.id === fresh.id ? fresh : item)),
    );

  return (
    <>
      <PageHeader
        title="Согласование"
        subtitle="Пять подписей до подачи. Собрать нужно за два часа до окончания приёма"
        action={
          counts.mine > 0 ? (
            <span className="text-sm text-ink-secondary">
              ждут вас <b className="font-semibold text-ink">{counts.mine}</b>
            </span>
          ) : (
            <span className="text-sm text-ink-muted">
              на согласовании {all.length}
            </span>
          )
        }
      />

      <Page>
        <Tabs tabs={TABS} value={tab} counts={counts} onChange={setTab} />

        {isLoading ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем согласования…" />
          </Panel>
        ) : error ? (
          <Panel>
            <EmptyState
              title="Список не открылся"
              description={
                error instanceof Error ? error.message : "Попробуйте обновить"
              }
            />
          </Panel>
        ) : shown.length === 0 ? (
          <Panel>
            <EmptyState
              title={tab === "mine" ? "Вас никто не ждёт" : "Здесь пусто"}
              description={
                tab === "mine"
                  ? "Все подписи, которые ставите вы, уже стоят."
                  : "Лоты попадают сюда с разбора, когда доходят до согласования."
              }
            />
          </Panel>
        ) : (
          <Panel className="overflow-hidden">
            <Head />
            <ul>
              {shown.map((card) => (
                <Row key={card.id} card={card} onDone={refresh} />
              ))}
            </ul>
          </Panel>
        )}
      </Page>
    </>
  );
}

const GRID =
  "grid grid-cols-[5.5rem_minmax(0,1fr)_8rem_7.5rem_repeat(5,5.5rem)] items-center gap-x-3";

function Head() {
  return (
    <div
      className={cx(
        GRID,
        "border-b border-hairline bg-plane px-5 py-2",
        "text-xs font-medium tracking-wide text-ink-muted uppercase",
      )}
    >
      <span>Код</span>
      <span>Закупка</span>
      <span className="text-right">Сумма, ₸</span>
      <span>Подписать до</span>
      {KINDS.map((kind) => (
        <span key={kind} className="text-center">
          {TITLES[kind]}
        </span>
      ))}
    </div>
  );
}

function Row({ card, onDone }: { card: Card; onDone: (fresh: Card) => void }) {
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

  const by = new Map(card.approvals.map((item) => [item.kind, item]));

  return (
    <li className="border-b border-hairline last:border-0">
      <div className={cx(GRID, "px-5 py-2.5")}>
        <Link
          to={`/work/lots/${card.id}`}
          className="font-mono text-xs text-ink-muted hover:text-ink"
        >
          {card.code}
        </Link>

        <Link to={`/work/lots/${card.id}`} className="min-w-0 hover:underline">
          <span className="block truncate text-sm text-ink">{card.title}</span>
          <span className="mt-0.5 block truncate text-xs text-ink-muted">
            {card.customer || card.row_id}
          </span>
        </Link>

        <span className="text-right text-sm tabular-nums text-ink-secondary">
          {card.amount === null ? "—" : money(card.amount)}
        </span>

        <ApproveBy card={card} />

        {KINDS.map((kind) => {
          const sign = by.get(kind);
          return (
            <Mark
              key={kind}
              sign={sign}
              busy={put.isPending}
              onYes={() => put.mutate({ kind, ok: true, note: "" })}
              onNo={() => setAsking(kind)}
            />
          );
        })}
      </div>

      {asking && (
        <div className="flex flex-wrap items-start gap-2 border-t border-hairline bg-plane px-5 py-2.5">
          <input
            value={why}
            onChange={(event) => setWhy(event.target.value)}
            autoFocus
            placeholder={`Что мешает согласовать · ${TITLES[asking]}`}
            className={cx(
              "h-8 min-w-0 flex-1 rounded-[8px] border border-baseline bg-surface px-3",
              "text-sm text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <button
            type="button"
            disabled={!why.trim() || put.isPending}
            onClick={() => put.mutate({ kind: asking, ok: false, note: why })}
            className="h-8 rounded-[8px] border border-critical px-3 text-sm text-critical transition hover:bg-critical/10 disabled:opacity-45"
          >
            Не согласовать
          </button>
          <button
            type="button"
            onClick={() => setAsking(null)}
            className="h-8 rounded-[8px] px-3 text-sm text-ink-secondary transition hover:bg-surface"
          >
            Отмена
          </button>
        </div>
      )}

      {/* Причины отказов — под строкой. Без них колонка с отказом говорит,
          что лот стоит, но не говорит, что чинить. */}
      {card.approvals
        .filter((item) => item.state === "rejected" && item.note)
        .map((item) => (
          <p
            key={item.kind}
            className="border-t border-hairline px-5 py-2 text-sm text-ink-secondary"
          >
            <span className="text-ink-muted">{item.name}</span> {item.note}
          </p>
        ))}
    </li>
  );
}

/**
 * Срок сбора подписей.
 *
 * Отдельно от срока приёма и раньше него. Показывать здесь общий срок значит
 * дать человеку два лишних часа, которых у него нет.
 */
function ApproveBy({ card }: { card: Card }) {
  if (!card.approve_left) {
    return <span className="text-sm text-ink-muted">—</span>;
  }
  if (card.approve_overdue) {
    return (
      <span className="text-sm font-medium text-critical">срок вышел</span>
    );
  }
  return (
    <span
      className={cx(
        "text-sm tabular-nums whitespace-nowrap",
        card.approve_burning
          ? "font-semibold text-critical"
          : "text-ink-secondary",
      )}
    >
      {card.approve_left}
    </span>
  );
}

function Mark({
  sign,
  busy,
  onYes,
  onNo,
}: {
  sign: Sign | undefined;
  busy: boolean;
  onYes: () => void;
  onNo: () => void;
}) {
  if (!sign)
    return <span className="text-center text-sm text-ink-muted">—</span>;

  if (sign.state === "approved") {
    return (
      <span
        className="truncate text-center text-sm text-good"
        title={sign.by ? `Согласовал ${sign.by}` : "Согласовано"}
      >
        согласен
      </span>
    );
  }
  if (sign.state === "rejected") {
    return (
      <span
        className="truncate text-center text-sm font-medium text-critical"
        title={sign.note}
      >
        против
      </span>
    );
  }
  if (!sign.can_sign) {
    return <span className="text-center text-sm text-ink-muted">ждём</span>;
  }
  return (
    <span className="flex justify-center gap-1">
      <button
        type="button"
        disabled={busy}
        onClick={onYes}
        className="rounded-[6px] border border-good/50 px-2 py-0.5 text-xs text-good transition hover:bg-good/10 disabled:opacity-45"
      >
        Да
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={onNo}
        className="rounded-[6px] px-2 py-0.5 text-xs text-ink-muted transition hover:bg-plane disabled:opacity-45"
      >
        Нет
      </button>
    </span>
  );
}

function belongs(card: Card, tab: Tab): boolean {
  if (tab === "ready") return card.approved;
  if (tab === "rejected")
    return card.approvals.some((item) => item.state === "rejected");
  if (tab === "waiting") return !card.approved;
  return card.approvals.some(
    (item) => item.can_sign && item.state === "waiting",
  );
}

function countBy(all: Card[]): Record<Tab, number> {
  const counts: Record<Tab, number> = {
    mine: 0,
    waiting: 0,
    rejected: 0,
    ready: 0,
  };
  for (const card of all) {
    for (const tab of ["mine", "waiting", "rejected", "ready"] as Tab[]) {
      if (belongs(card, tab)) counts[tab] += 1;
    }
  }
  return counts;
}
