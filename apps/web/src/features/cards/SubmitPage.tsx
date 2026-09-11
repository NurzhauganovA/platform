/**
 * Подача: календарь и итоги.
 *
 * Календарь, а не список. Подают в назначенную минуту, и вопрос у менеджера
 * утром один — что сегодня и во сколько. Список, отсортированный по сроку,
 * отвечает на него хуже: он не показывает, что на четверг ничего нет, а на
 * пятницу шесть подач подряд.
 *
 * День — заголовок, подачи внутри по часам. Пустые дни не рисуются: месяц
 * пустых клеток ради трёх заполненных — это экран, по которому надо искать.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cardsApi, type Card } from "@/api/cards";
import { ApiError } from "@/api/client";
import { PageHeader } from "@/shell/AppShell";
import {
  Button,
  Card as Panel,
  EmptyState,
  Page,
  Spinner,
  Tabs,
  cx,
  money,
} from "@/ui";

type Tab = "soon" | "awaiting" | "results";

const TABS: { key: Tab; title: string }[] = [
  { key: "soon", title: "К подаче" },
  { key: "awaiting", title: "Ждём итоги" },
  { key: "results", title: "Итоги" },
];

export function SubmitPage() {
  const [tab, setTab] = useState<Tab>("soon");
  const cache = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["cards"],
    queryFn: () => cardsApi.list(),
    refetchInterval: 60_000,
  });

  const all = data ?? [];
  const groups = useMemo(
    () => byDay(all.filter((item) => belongs(item, tab))),
    [all, tab],
  );
  const counts: Record<Tab, number> = {
    soon: all.filter((item) => belongs(item, "soon")).length,
    awaiting: all.filter((item) => belongs(item, "awaiting")).length,
    results: all.filter((item) => belongs(item, "results")).length,
  };

  const refresh = (fresh: Card) =>
    cache.setQueryData<Card[]>(["cards"], (old) =>
      (old ?? []).map((item) => (item.id === fresh.id ? fresh : item)),
    );

  return (
    <>
      <PageHeader
        title="Подача"
        subtitle="Когда подавать, что подано и чем кончилось"
        action={
          counts.soon > 0 ? (
            <span className="text-sm text-ink-secondary">
              к подаче <b className="font-semibold text-ink">{counts.soon}</b>
            </span>
          ) : (
            <span className="text-sm text-ink-muted">подавать нечего</span>
          )
        }
      />

      <Page>
        <Tabs tabs={TABS} value={tab} counts={counts} onChange={setTab} />

        {isLoading ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем подачи…" />
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
        ) : !groups.length ? (
          <Panel>
            <EmptyState
              title="Здесь пусто"
              description={
                tab === "soon"
                  ? "Лоты попадают сюда, когда собраны все подписи и они объявлены готовыми к участию."
                  : "Подайте лот, и он появится здесь."
              }
            />
          </Panel>
        ) : (
          <div className="space-y-4">
            {groups.map(([day, lots]) => (
              <Day key={day} day={day} lots={lots} tab={tab} onDone={refresh} />
            ))}
          </div>
        )}
      </Page>
    </>
  );
}

function Day({
  day,
  lots,
  tab,
  onDone,
}: {
  day: string;
  lots: Card[];
  tab: Tab;
  onDone: (fresh: Card) => void;
}) {
  return (
    <Panel className="overflow-hidden">
      <header className="flex items-baseline justify-between gap-4 border-b border-hairline bg-plane px-4 py-2">
        <h2 className="text-sm font-semibold text-ink">{day}</h2>
        <span className="text-xs tabular-nums text-ink-muted">
          {lots.length} {lots.length === 1 ? "подача" : "подач"}
        </span>
      </header>
      <ul className="divide-y divide-hairline">
        {lots.map((card) => (
          <Row key={card.id} card={card} tab={tab} onDone={onDone} />
        ))}
      </ul>
    </Panel>
  );
}

function Row({
  card,
  tab,
  onDone,
}: {
  card: Card;
  tab: Tab;
  onDone: (fresh: Card) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [amount, setAmount] = useState("");
  const [winner, setWinner] = useState("");
  // Сумма участия — отдельным полем от суммы итогов. Их спрашивают в разное
  // время и на разных вкладках, и одно поле на двоих означало бы, что
  // недописанная цена победителя уезжает в подачу.
  const [bid, setBid] = useState("");
  const [naming, setNaming] = useState(false);
  const [trouble, setTrouble] = useState("");

  const move = useMutation({
    mutationFn: (to: "awaiting" | "won" | "lost") => cardsApi.move(card.id, to),
    onSuccess: onDone,
  });
  const result = useMutation({
    mutationFn: () =>
      cardsApi.result(card.id, amount ? Number(amount) : null, winner),
    onSuccess: (fresh) => {
      setAsking(false);
      onDone(fresh);
    },
  });
  const submit = useMutation({
    mutationFn: () => cardsApi.submit(card.id, Number(bid)),
    onSuccess: (fresh) => {
      setNaming(false);
      setTrouble("");
      setBid("");
      onDone(fresh);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не отметилось"),
  });

  return (
    <li>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
        <span className="w-12 text-sm tabular-nums font-medium text-ink">
          {clock(card.deadline)}
        </span>

        <Link
          to={`/work/lots/${card.id}`}
          className="font-mono text-xs text-ink-muted hover:text-ink"
        >
          {card.code}
        </Link>

        <Link
          to={`/work/lots/${card.id}`}
          className="min-w-0 flex-1 hover:underline"
        >
          <span className="block truncate text-sm text-ink">{card.title}</span>
          <span className="mt-0.5 block truncate text-xs text-ink-muted">
            {card.customer || card.row_id}
          </span>
        </Link>

        <span className="text-sm tabular-nums text-ink-secondary">
          {card.amount === null ? "—" : `${money(card.amount)} ₸`}
        </span>

        {card.left && (
          <span
            className={cx(
              "w-28 text-sm tabular-nums",
              card.overdue
                ? "text-ink-muted"
                : card.burning
                  ? "font-semibold text-critical"
                  : "text-ink-secondary",
            )}
          >
            {card.left}
          </span>
        )}

        {tab === "soon" && card.can.includes("awaiting") && (
          <Button
            variant="primary"
            disabled={submit.isPending}
            onClick={() => setNaming((open) => !open)}
          >
            {naming ? "Не подавали" : "Подали"}
          </Button>
        )}

        {tab === "awaiting" && card.bid_amount !== null && (
          <span
            className="text-sm tabular-nums text-ink"
            title="За сколько подали заявку"
          >
            подали за {money(card.bid_amount)} ₸
          </span>
        )}

        {tab === "awaiting" && (
          <span className="flex gap-1.5">
            {card.can.includes("won") && (
              <Button
                variant="secondary"
                disabled={move.isPending}
                onClick={() => {
                  move.mutate("won");
                  setAsking(true);
                }}
              >
                Выиграли
              </Button>
            )}
            {card.can.includes("lost") && (
              <Button
                variant="ghost"
                disabled={move.isPending}
                onClick={() => {
                  move.mutate("lost");
                  setAsking(true);
                }}
              >
                Проиграли
              </Button>
            )}
          </span>
        )}

        {tab === "results" && (
          <span className="flex items-baseline gap-3 text-sm">
            <span
              className={cx(
                card.status === "lost" ? "text-ink-muted" : "text-good",
              )}
            >
              {card.status_name}
            </span>
            {card.won_amount !== null && (
              <span className="tabular-nums text-ink">
                {money(card.won_amount)} ₸
              </span>
            )}
            {card.winner && (
              <span className="truncate text-ink-secondary" title={card.winner}>
                {card.winner}
              </span>
            )}
            <button
              type="button"
              onClick={() => setAsking((open) => !open)}
              className="text-xs text-ink-muted underline decoration-hairline underline-offset-2 hover:text-ink"
            >
              {card.won_amount === null && !card.winner
                ? "вписать"
                : "поправить"}
            </button>
          </span>
        )}
      </div>

      {naming && (
        /* Сумму спрашиваем до отметки, а не после. Отметка без суммы — это то
           же самое «подали», ради замены которого всё и делалось: за сколько
           заходили, спрашивают, когда пришли итоги, и вспомнить через месяц
           уже некому. */
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline bg-plane px-4 py-2.5">
          <span className="text-[12.5px] text-ink-secondary">
            За сколько участвуем
          </span>
          <input
            value={bid}
            autoFocus
            inputMode="numeric"
            onChange={(event) =>
              setBid(event.target.value.replace(/[^\d]/g, ""))
            }
            onKeyDown={(event) => {
              if (event.key === "Enter" && Number(bid) > 0) submit.mutate();
              if (event.key === "Escape") setNaming(false);
            }}
            placeholder="8 660 625"
            className={cx(
              "w-40 rounded-[8px] border border-hairline bg-surface px-2.5 py-1.5",
              "text-sm tabular-nums text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <span className="text-[12.5px] text-ink-muted">₸</span>
          {card.amount !== null && (
            <span className="text-[11.5px] text-ink-muted">
              объявлено {money(card.amount)} ₸
            </span>
          )}
          <Button
            variant="primary"
            disabled={!(Number(bid) > 0) || submit.isPending}
            onClick={() => submit.mutate()}
          >
            {submit.isPending ? "Отмечаем…" : "Подал"}
          </Button>
          {trouble && (
            <span className="text-[12.5px] text-critical">{trouble}</span>
          )}
        </div>
      )}

      {asking && (
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline bg-plane px-4 py-2.5">
          <input
            value={amount}
            inputMode="numeric"
            onChange={(event) =>
              setAmount(event.target.value.replace(/[^\d]/g, ""))
            }
            placeholder="Цена, с которой выиграли"
            className={cx(
              "h-8 w-52 rounded-[8px] border border-baseline bg-surface px-2.5",
              "text-sm tabular-nums text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <input
            value={winner}
            onChange={(event) => setWinner(event.target.value)}
            placeholder="Кто выиграл, если не мы"
            className={cx(
              "h-8 min-w-0 flex-1 rounded-[8px] border border-baseline bg-surface px-2.5",
              "text-sm text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <Button
            variant="secondary"
            disabled={(!amount && !winner.trim()) || result.isPending}
            onClick={() => result.mutate()}
          >
            Записать
          </Button>
          <Button variant="ghost" onClick={() => setAsking(false)}>
            Отмена
          </Button>
        </div>
      )}

      {(move.error || result.error) && (
        <p className="border-t border-hairline px-4 py-2 text-sm text-critical">
          {(move.error ?? result.error) instanceof Error
            ? (move.error ?? result.error)!.message
            : "Не получилось"}
        </p>
      )}
    </li>
  );
}

function belongs(card: Card, tab: Tab): boolean {
  if (tab === "soon") return card.status === "ready";
  if (tab === "awaiting") return card.status === "awaiting";
  return [
    "won",
    "lost",
    "contract",
    "fulfilling",
    "awaiting_payment",
    "done",
  ].includes(card.status);
}

/**
 * Раскладка по дням.
 *
 * Пустые дни не создаются: месяц пустых клеток ради трёх заполненных — это
 * экран, по которому приходится искать.
 */
function byDay(lots: Card[]): [string, Card[]][] {
  const days = new Map<string, Card[]>();
  for (const card of lots) {
    const day = card.deadline ? dayName(card.deadline) : "Без срока";
    const bucket = days.get(day);
    if (bucket) bucket.push(card);
    else days.set(day, [card]);
  }
  for (const bucket of days.values()) {
    bucket.sort((a, b) => (a.deadline > b.deadline ? 1 : -1));
  }
  return [...days.entries()];
}

function dayName(iso: string): string {
  const when = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const words = when.toLocaleDateString("ru-KZ", {
    day: "numeric",
    month: "long",
    weekday: "long",
  });
  if (same(when, today)) return `Сегодня · ${words}`;
  if (same(when, tomorrow)) return `Завтра · ${words}`;
  return words[0].toUpperCase() + words.slice(1);
}

function clock(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("ru-KZ", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
