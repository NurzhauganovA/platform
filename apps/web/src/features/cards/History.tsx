/**
 * Кто работал над лотом.
 *
 * Заводилось ради вопроса «кому платить премию». Из карточки этого не видно:
 * она показывает итог, а по итогу премию делить нельзя — у лота, который вёл
 * один человек, и у лота, прошедшего через пятерых, итог одинаковый.
 *
 * Сверху четыре числа, ниже полосы этапов со временем, ниже сама лента.
 * Считает сервер: по этим числам делят деньги, и второй расчёт здесь однажды
 * разошёлся бы с первым.
 *
 * Лента раскладкой в три колонки — когда, кто, что. Одинаковая ширина у
 * времени и у имени держит взгляд на одной вертикали: по такой ленте видно,
 * что за день сделал конкретный человек, не читая её строку за строкой.
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
import { ROLE_NAMES, BarHead, BarTitle, Note, shortName, stamp } from "./kit";

export function History({ card }: { card: Card }) {
  const { data, isLoading } = useQuery({
    queryKey: ["cards", card.id, "history"],
    queryFn: () => cardsApi.history(card.id),
  });

  if (isLoading) {
    return (
      <Panel className="px-[15px] py-[15px]">
        <Spinner label="Читаем историю…" />
      </Panel>
    );
  }

  if (!data || data.events.length === 0) {
    return (
      <Panel>
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
    <div className="space-y-2.5">
      {/* Четыре числа в ряд через волосяную линию. Плитками, а не строками:
          вопрос к ним один — «много это или мало», — и рядом друг с другом
          они сравниваются взглядом. */}
      <Panel className="overflow-hidden">
        <div className="grid grid-cols-4 gap-px bg-hairline max-[900px]:grid-cols-2">
          <Tile
            label="Участвовало людей"
            value={String(data.workers.length)}
            hint={departments(data.workers)}
          />
          <Tile
            label="Действий"
            value={String(data.events.length)}
            hint={`${people} ${people === 1 ? "человеком" : "людьми"}, ${machine} прогонами`}
          />
          <Tile
            label="Больше всех"
            value={top ? shortName(top.name) : "—"}
            hint={
              top
                ? [
                    `${top.actions} ${plural(top.actions)}`,
                    ROLE_NAMES[top.role] || top.role,
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : ""
            }
            small
          />
          <Tile
            label="Лот в работе"
            value={spread(data.stages)}
            hint={since ? `с ${stamp(since)}` : ""}
          />
        </div>
      </Panel>

      {data.stages.length > 0 && <Stages stages={data.stages} />}

      <Panel className="overflow-hidden">
        <BarHead>
          <BarTitle>Что делали</BarTitle>
          <Note className="ml-auto">по этому считаем премию</Note>
        </BarHead>
        <ol>
          {data.events.map((event) => (
            <Line key={event.id} event={event} />
          ))}
        </ol>
      </Panel>
    </div>
  );
}

function Tile({
  label,
  value,
  hint,
  small,
}: {
  label: string;
  value: string;
  hint: string;
  small?: boolean;
}) {
  return (
    <div className="min-w-0 bg-surface px-3.5 py-3">
      <p className="truncate text-[11.5px] text-ink-muted">{label}</p>
      <p
        className={cx(
          "mt-1 truncate font-semibold tracking-[-0.02em] text-ink",
          small ? "text-[14px]" : "text-[19px] tabular-nums",
        )}
        title={value}
      >
        {value}
      </p>
      <p className="truncate text-[11.5px] text-ink-muted">{hint}</p>
    </div>
  );
}

/**
 * Сколько лот простоял на каждом этапе и у кого.
 *
 * Отвечает на «где застряло». Одно число «в работе сутки» этого не говорит:
 * сутки в разборе и сутки на согласовании — разные разговоры и разные люди.
 *
 * Полоса под каждым этапом — доля от самого длинного, а не от всего пути:
 * этап в двадцать минут рядом с этапом в неделю иначе не виден вовсе.
 */
function Stages({ stages }: { stages: Stage[] }) {
  const longest = Math.max(...stages.map((item) => item.seconds), 1);

  return (
    <Panel className="overflow-hidden">
      <BarHead>
        <BarTitle>Сколько держали в статусе</BarTitle>
        <Note className="ml-auto">по самому длинному видно, где застряло</Note>
      </BarHead>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-x-[18px] gap-y-3 px-[15px] py-3.5">
        {stages.map((stage, index) => (
          <div key={`${stage.status}-${index}`} className="min-w-0">
            <span
              aria-hidden
              className="block h-[3px] rounded-sm bg-hairline"
            >
              <span
                className={cx(
                  "block h-full rounded-sm bg-series-1",
                  !stage.running && "opacity-45",
                )}
                style={{
                  width: `${Math.max(Math.round((stage.seconds / longest) * 100), 4)}%`,
                }}
              />
            </span>
            <p className="mt-1.5 truncate text-[12.5px] font-medium text-ink">
              {stage.name}
              {/* Идущий этап помечен словом, а не одним цветом полосы: полоса
                  у него такая же, а разница между «держали» и «держим» — это
                  разница между отчётом и работой. */}
              {stage.running && (
                <span className="font-normal text-series-1"> · идёт</span>
              )}
            </p>
            <p className="truncate text-[11.5px] text-ink-muted tabular-nums">
              {lasted(stage.seconds)}
              {stage.owner && ` · ${shortName(stage.owner)}`}
            </p>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Line({ event }: { event: LotEvent }) {
  return (
    <li
      className={cx(
        "grid grid-cols-[96px_170px_minmax(0,1fr)] gap-3 border-t border-hairline/70 px-[15px] py-[11px]",
        "max-[900px]:grid-cols-1 max-[900px]:gap-1",
        // Автоматические приглушены: их видно, но взгляд по ним не цепляется.
        event.by_machine && "bg-plane/50",
      )}
    >
      <time
        dateTime={event.at}
        className="text-[11.5px] whitespace-nowrap text-ink-muted tabular-nums"
      >
        {stamp(event.at)}
      </time>

      <span className="min-w-0">
        <span
          className={cx(
            "block truncate text-[12.5px]",
            event.by_machine ? "text-ink-muted" : "font-medium text-ink",
          )}
        >
          {event.by_machine
            ? "автоматически"
            : shortName(event.actor) || event.actor}
        </span>
        <span className="block truncate text-[11.5px] text-ink-muted">
          {event.by_machine
            ? "в рейтинг не идёт"
            : ROLE_NAMES[event.actor_role] || event.actor_role}
        </span>
      </span>

      <span className="min-w-0 text-[12.5px] text-ink">
        {event.title}
        {event.detail && (
          <span className="block text-[11.5px] text-ink-muted">
            {event.detail}
          </span>
        )}
      </span>
    </li>
  );
}

function departments(workers: Worker[]): string {
  const roles = new Set(workers.map((item) => item.role).filter(Boolean));
  if (roles.size === 0) return "";
  return `из ${roles.size} ${roles.size === 1 ? "отдела" : "отделов"}`;
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
