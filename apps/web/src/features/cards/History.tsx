/**
 * Кто работал над лотом.
 *
 * Заводилось ради вопроса «кому платить премию». Из карточки этого не видно:
 * она показывает итог, а по итогу премию делить нельзя — у лота, который вёл
 * один человек, и у лота, прошедшего через пятерых, итог одинаковый.
 *
 * Сверху четыре числа, ниже полоса этапов со временем, ниже сама лента.
 * Считает сервер: по этим числам делят деньги, и второй расчёт здесь однажды
 * разошёлся бы с первым.
 *
 * Прогоны и модель из ленты не выбрасываются, но в сводку не идут: знать, что
 * замечание написала модель, важно, а премию получает человек.
 */

import { useQuery } from "@tanstack/react-query";
import {
  cardsApi,
  type Card,
  type LotEvent,
  type Stage,
  type Worker,
} from "@/api/cards";
import { Card as Panel, EmptyState, Spinner, cx } from "@/ui";

const ROLE_NAMES: Record<string, string> = {
  admin: "администратор",
  analyst: "тендерщик",
  manager: "менеджер",
  head: "руководитель",
  commercial: "комдир",
  buyer: "снабжение",
  technologist: "технолог",
  assembler: "сборщик",
  lawyer: "юрист",
  viewer: "наблюдатель",
};

export function History({ card }: { card: Card }) {
  const { data, isLoading } = useQuery({
    queryKey: ["cards", card.id, "history"],
    queryFn: () => cardsApi.history(card.id),
  });

  if (isLoading) {
    return (
      <Panel className="px-5 py-6">
        <Spinner label="Читаем историю…" />
      </Panel>
    );
  }

  if (!data || data.events.length === 0) {
    return (
      <Panel className="px-5 py-8">
        <EmptyState
          title="Пока никто ничего не делал"
          description="Здесь появится всё: кто взял в работу, кто перевёл, кто подписал и кто закрыл задачу. История ведётся с того дня, как её завели, — прошлое восстановить неоткуда."
        />
      </Panel>
    );
  }

  const people = data.events.filter((item) => !item.by_machine).length;
  const machine = data.events.length - people;
  const top = data.workers[0];
  const since = data.events[data.events.length - 1]?.at ?? "";

  return (
    <Panel>
      <div className="grid grid-cols-4 border-b border-hairline">
        <Tile
          label="Участвовало людей"
          value={String(data.workers.length)}
          hint={departments(data.workers)}
        />
        <Tile
          label="Действий"
          value={String(data.events.length)}
          hint={`${people} людьми, ${machine} автоматических`}
        />
        <Tile
          label="Больше всех"
          value={top?.name ?? "—"}
          hint={
            top
              ? `${top.actions} ${plural(top.actions)} · ${ROLE_NAMES[top.role] || top.role}`
              : ""
          }
          small
        />
        <Tile
          label="Лот в работе"
          value={spread(data.stages)}
          hint={since ? `с ${short(since)}` : ""}
          last
        />
      </div>

      {data.stages.length > 0 && <Stages stages={data.stages} />}

      <ol className="divide-y divide-hairline">
        {data.events.map((event) => (
          <Line key={event.id} event={event} />
        ))}
      </ol>
    </Panel>
  );
}

function Tile({
  label,
  value,
  hint,
  small,
  last,
}: {
  label: string;
  value: string;
  hint: string;
  small?: boolean;
  last?: boolean;
}) {
  return (
    <div
      className={cx("min-w-0 px-5 py-3", !last && "border-r border-hairline")}
    >
      <p className="text-xs text-ink-muted">{label}</p>
      <p
        className={cx(
          "mt-0.5 truncate font-semibold text-ink",
          small ? "text-[15px]" : "text-xl tabular-nums",
        )}
        title={value}
      >
        {value}
      </p>
      <p className="truncate text-xs text-ink-muted">{hint}</p>
    </div>
  );
}

/**
 * Сколько лот простоял на каждом этапе и у кого.
 *
 * Отвечает на «где застряло». Одно число «в работе сутки» этого не говорит:
 * сутки в разборе и сутки на согласовании — разные разговоры и разные люди.
 */
function Stages({ stages }: { stages: Stage[] }) {
  const longest = Math.max(...stages.map((item) => item.seconds), 1);
  return (
    <div className="grid grid-cols-4 gap-x-4 gap-y-3 border-b border-hairline px-5 py-3">
      {stages.map((stage, index) => (
        <div key={`${stage.status}-${index}`} className="min-w-0">
          <span
            aria-hidden
            className={cx(
              "block h-1 rounded-full",
              stage.running ? "bg-series-1" : "bg-series-1/35",
            )}
            style={{
              width: `${Math.max(Math.round((stage.seconds / longest) * 100), 8)}%`,
            }}
          />
          <p className="mt-1.5 truncate text-sm text-ink">
            {stage.name} — {lasted(stage.seconds)}
            {stage.running && <span className="text-series-1"> · идёт</span>}
          </p>
          <p className="truncate text-xs text-ink-muted">
            {stage.owner ? `у ${stage.owner}` : "без ответственного"}
          </p>
        </div>
      ))}
    </div>
  );
}

function Line({ event }: { event: LotEvent }) {
  return (
    <li
      className={cx(
        "flex gap-4 px-5 py-2.5",
        // Автоматические приглушены: их видно, но взгляд по ним не цепляется.
        event.by_machine && "bg-plane/50",
      )}
    >
      <time
        dateTime={event.at}
        className="w-28 shrink-0 text-xs whitespace-nowrap text-ink-muted tabular-nums"
      >
        {short(event.at)}
      </time>

      <span className="w-44 shrink-0 min-w-0">
        <span
          className={cx(
            "block truncate text-sm",
            event.by_machine ? "font-mono text-xs text-ink-muted" : "text-ink",
          )}
        >
          {event.by_machine ? event.actor_role || "автоматически" : event.actor}
        </span>
        <span className="block truncate text-xs text-ink-muted">
          {event.by_machine
            ? "автоматически"
            : ROLE_NAMES[event.actor_role] || event.actor_role}
        </span>
      </span>

      <span className="min-w-0 flex-1">
        <span className="block text-sm text-ink">{event.title}</span>
        {event.detail && (
          <span className="mt-0.5 block text-xs text-ink-secondary">
            {event.detail}
          </span>
        )}
      </span>

      {event.by_machine && (
        <span className="shrink-0 self-center text-xs whitespace-nowrap text-ink-muted">
          в рейтинг не идёт
        </span>
      )}
    </li>
  );
}

function departments(workers: Worker[]): string {
  const roles = new Set(workers.map((item) => item.role).filter(Boolean));
  if (roles.size === 0) return "";
  return `из ${roles.size} ${roles.size === 1 ? "отдела" : roles.size < 5 ? "отделов" : "отделов"}`;
}

function plural(count: number): string {
  const tail =
    count % 100 > 4 && count % 100 < 21
      ? 2
      : [2, 0, 1, 1, 1, 2][Math.min(count % 10, 5)];
  return ["действие", "действия", "действий"][tail];
}

/** «1 д. 5 ч.» — крупные разряды, мелкие не нужны на длинных сроках. */
function lasted(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days} д. ${hours} ч.`;
  if (hours > 0) return `${hours} ч. ${minutes} мин.`;
  return `${minutes} мин.`;
}

function spread(stages: Stage[]): string {
  const total = stages.reduce((sum, item) => sum + item.seconds, 0);
  return total > 0 ? lasted(total) : "—";
}

function short(at: string): string {
  return new Date(at).toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
