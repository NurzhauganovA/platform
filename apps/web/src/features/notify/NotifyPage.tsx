/**
 * Уведомления: работают или нет и почему.
 *
 * Экран заведён потому, что молчание уведомлений выглядит одинаково при пяти
 * разных причинах: сервис не поднят, до него нет хода из контейнера, ключи
 * разошлись, человека нет в реестре, Телеграм не привязан. Разбирать это
 * приходилось по журналам трёх наборов контейнеров — с сервера, по ssh, вечером.
 *
 * Сверху состояние цепочки, ниже люди. Порядок не случаен: пока не дошли до
 * сервиса, список людей не значит ничего, и смотреть в него — потерянное время.
 *
 * Реестр — у сервиса, и это видно на экране. Строка «сервис его не знает»
 * отвечает на самый частый случай: выгрузка сотрудников идёт при запуске
 * платформы, и если сервис в тот момент лежал, реестр остаётся пустым до
 * следующей перезагрузки. Кнопка рядом чинит это, не трогая платформу.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  notifyApi,
  type NotifyPerson,
  type NotifyState,
  type Sent,
} from "@/api/notify";
import { ApiError } from "@/api/client";
import { PageHeader } from "@/shell/AppShell";
import { Button, Card as Panel, EmptyState, Page, Spinner, cx } from "@/ui";

export function NotifyPage() {
  const cache = useQueryClient();
  const [trouble, setTrouble] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const { data: state, isLoading } = useQuery({
    queryKey: ["notify", "state"],
    queryFn: notifyApi.state,
    // Состояние сервиса меняется без нашего участия: его поднимают и роняют
    // рядом. Раз в полминуты — чтобы открытый экран не врал часами.
    refetchInterval: 30_000,
  });
  const { data: people } = useQuery({
    queryKey: ["notify", "people"],
    queryFn: notifyApi.people,
    enabled: Boolean(state?.reachable),
  });

  const sync = useMutation({
    mutationFn: notifyApi.sync,
    onSuccess: () => {
      setTrouble("");
      void cache.invalidateQueries({ queryKey: ["notify"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не вышло"),
  });

  if (isLoading || !state) {
    return (
      <Page>
        <PageHeader
          title="Уведомления"
          subtitle="Доходят ли сообщения до людей"
        />
        <Spinner label="Спрашиваем сервис…" />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Уведомления"
        subtitle="Доходят ли сообщения до людей и почему нет"
      />

      <div className="space-y-3">
        <Chain state={state} />

        {trouble && (
          <p
            role="alert"
            className="rounded-[10px] border border-critical/40 bg-critical/10 px-[15px] py-2.5 text-[12.5px] text-ink"
          >
            {trouble}
          </p>
        )}

        {state.reachable && (
          <Registry
            state={state}
            busy={sync.isPending}
            onSync={() => sync.mutate()}
          />
        )}

        {state.reachable && (
          <People
            people={people ?? []}
            open={open}
            onOpen={(id) => setOpen((was) => (was === id ? null : id))}
          />
        )}
      </div>
    </Page>
  );
}

/**
 * Цепочка по звеньям.
 *
 * Звенья идут в том порядке, в каком рвутся, и первое порвавшееся объясняется
 * словами — вместе с тем, что именно поправить. Показывать дальше нечего:
 * состояние людей за оборванной связью — это данные прошлой недели.
 */
function Chain({ state }: { state: NotifyState }) {
  return (
    <Panel className="overflow-hidden">
      <div className="border-b border-hairline/70 px-[15px] py-2.5">
        <h2 className="text-[13.5px] font-semibold text-ink">Связь</h2>
      </div>

      <Link
        ok={state.configured}
        title="Настроено в платформе"
        detail={
          state.configured
            ? state.url
            : "PLATFORM__NOTIFY__URL и PLATFORM__NOTIFY__TOKEN пусты — уведомления выключены"
        }
      />
      {state.configured && (
        <Link
          ok={state.reachable}
          title="Сервис отвечает"
          detail={
            state.reachable ? `окружение ${state.environment}` : state.trouble
          }
        />
      )}
      {state.reachable && (
        <>
          <Link
            ok={state.database}
            title="База сервиса жива"
            detail={
              state.database
                ? "сводка рассылки собирается"
                : "сводку собрать не вышло: у сервиса недоступна база. Его собственная готовность этого не показывает"
            }
          />
          <Link
            ok={state.telegram}
            title="Телеграм настроен"
            detail={
              state.telegram
                ? "ключ бота задан"
                : "NOTIFY__TELEGRAM__TOKEN пуст"
            }
          />
          <Link
            ok={state.email}
            title="Почта настроена"
            detail={
              state.email
                ? "ящик и отправитель заданы"
                : "NOTIFY__SMTP__HOST или FROM_ADDRESS пусты: код привязки отправить нечем"
            }
          />
        </>
      )}

      {state.problems.length > 0 && (
        <div className="border-t border-hairline/70 px-[15px] py-2.5">
          {state.problems.map((one) => (
            <p key={one} className="text-[12.5px] text-ink-secondary">
              — {one}
            </p>
          ))}
        </div>
      )}
    </Panel>
  );
}

/**
 * Одно звено.
 *
 * Значок рядом с цветом, а не вместо: зелёное и красное при дальтонизме
 * неразличимы, и экран, который отвечает «работает или нет» одним оттенком,
 * половине людей не отвечает вовсе.
 */
function Link({
  ok,
  title,
  detail,
}: {
  ok: boolean;
  title: string;
  detail: string;
}) {
  return (
    <div className="flex items-start gap-2.5 border-b border-hairline/70 px-[15px] py-2.5 last:border-b-0">
      <span
        aria-hidden
        className={cx(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
          ok ? "bg-good/15 text-good" : "bg-critical/15 text-critical",
        )}
      >
        {ok ? "✓" : "✕"}
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] text-ink">
          {title}
          <span className="sr-only">
            {ok ? " — в порядке" : " — не работает"}
          </span>
        </span>
        {detail && (
          <span className="block text-[11.5px] text-ink-muted">{detail}</span>
        )}
      </span>
    </div>
  );
}

/**
 * Реестр: сколько людей у нас и сколько у сервиса.
 *
 * Два числа рядом отвечают на вопрос, который иначе стоит перезагрузки
 * платформы: ноль против десяти — это не «никому не приходит», а «сервис не
 * знает никого».
 */
function Registry({
  state,
  busy,
  onSync,
}: {
  state: NotifyState;
  busy: boolean;
  onSync: () => void;
}) {
  const empty = state.recipients === 0 && state.people_here > 0;

  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-hairline/70 px-[15px] py-2.5">
        <h2 className="text-[13.5px] font-semibold text-ink">
          Реестр и рассылка
        </h2>
        <Button variant="secondary" disabled={busy} onClick={onSync}>
          {busy ? "Выгружаем…" : "Выгрузить сотрудников"}
        </Button>
      </div>

      {empty && (
        <p className="border-b border-hairline/70 bg-warning/10 px-[15px] py-2.5 text-[12.5px] text-ink">
          Сервис не знает ни одного сотрудника, а в платформе их{" "}
          {state.people_here}. Пока реестр пуст, бот на присланную почту
          отвечает «если такая почта заведена, код отправлен» и не отправляет
          ничего: ответ одинаков для известного и неизвестного адреса намеренно
          — иначе по нему проверяют, кто у нас работает. Нажмите «Выгрузить
          сотрудников».
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-[15px] py-[11px] sm:grid-cols-4">
        <Count title="В платформе" value={state.people_here} />
        <Count title="В реестре сервиса" value={state.recipients} />
        <Count title="Привязан Телеграм" value={state.telegram_linked} />
        <Count title="Сейчас в очереди" value={state.pending} />
        <Count title="Отправлено за сутки" value={state.sent_24h} />
        <Count title="Не дошло за сутки" value={state.failed_24h} />
        <Count
          title="Пропущено за сутки"
          value={state.skipped_24h}
          hint="Отправлять было нечем: канал выключен или не привязан"
        />
      </dl>
    </Panel>
  );
}

function Count({
  title,
  value,
  hint,
}: {
  title: string;
  value: number;
  hint?: string;
}) {
  return (
    <div title={hint}>
      <dt className="text-[11.5px] text-ink-muted">{title}</dt>
      <dd className="text-[17px] font-semibold text-ink tabular-nums">
        {value}
      </dd>
    </div>
  );
}

/** Люди и их каналы. Нажатие раскрывает, что человеку отправляли. */
function People({
  people,
  open,
  onOpen,
}: {
  people: NotifyPerson[];
  open: string | null;
  onOpen: (id: string) => void;
}) {
  if (!people.length) {
    return (
      <Panel>
        <EmptyState
          title="Сотрудников нет"
          description="Заводит их make user на сервере."
        />
      </Panel>
    );
  }

  return (
    <Panel className="overflow-hidden">
      <div className="border-b border-hairline/70 px-[15px] py-2.5">
        <h2 className="text-[13.5px] font-semibold text-ink">Сотрудники</h2>
      </div>
      <ul>
        {people.map((one) => (
          <Person
            key={one.user_id}
            person={one}
            open={open === one.user_id}
            onOpen={() => onOpen(one.user_id)}
          />
        ))}
      </ul>
    </Panel>
  );
}

function Person({
  person,
  open,
  onOpen,
}: {
  person: NotifyPerson;
  open: boolean;
  onOpen: () => void;
}) {
  const cache = useQueryClient();
  const [trouble, setTrouble] = useState("");

  const { data: history } = useQuery({
    queryKey: ["notify", "history", person.user_id],
    queryFn: () => notifyApi.history(person.user_id),
    enabled: open,
  });

  const test = useMutation({
    mutationFn: () => notifyApi.test(person.user_id),
    onSuccess: () => {
      setTrouble("");
      void cache.invalidateQueries({
        queryKey: ["notify", "history", person.user_id],
      });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не отправилось"),
  });

  return (
    <li className="border-b border-hairline/70 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-[15px] py-2.5">
        <button
          type="button"
          onClick={onOpen}
          aria-expanded={open}
          className="min-w-0 flex-1 text-left"
        >
          <span className="block truncate text-[13px] font-medium text-ink">
            {person.full_name || person.email}
          </span>
          <span className="block truncate text-[11.5px] text-ink-muted">
            {person.email}
            {person.role && ` · ${person.role}`}
          </span>
        </button>

        <Mark
          ok={person.known}
          yes="в реестре"
          no="сервис не знает"
          hint={
            person.known
              ? ""
              : "Бот не найдёт эту почту и код не отправит. Лечится кнопкой «Выгрузить сотрудников»."
          }
        />
        <Mark
          ok={person.telegram_linked && person.telegram_enabled}
          yes={
            person.telegram_name ? `TG ${person.telegram_name}` : "TG привязан"
          }
          no={person.telegram_linked ? "TG выключен" : "TG не привязан"}
          hint={person.stop_reason}
        />
        <Mark ok={person.email_enabled} yes="почта" no="почта выключена" />

        <Button
          variant="ghost"
          disabled={!person.known || test.isPending}
          onClick={() => test.mutate()}
        >
          {test.isPending ? "Шлём…" : "Проверить"}
        </Button>
      </div>

      {trouble && (
        <p role="alert" className="px-[15px] pb-2.5 text-[12px] text-critical">
          {trouble}
        </p>
      )}

      {open && <History rows={history ?? []} />}
    </li>
  );
}

/** Признак с подписью: цвет один смысла не несёт. */
function Mark({
  ok,
  yes,
  no,
  hint,
}: {
  ok: boolean;
  yes: string;
  no: string;
  hint?: string;
}) {
  return (
    <span
      title={hint || undefined}
      className={cx(
        "shrink-0 rounded-[6px] px-1.5 py-0.5 text-[11px]",
        ok ? "bg-good/10 text-good" : "bg-critical/10 text-critical",
      )}
    >
      {ok ? "✓ " : "✕ "}
      {ok ? yes : no}
    </span>
  );
}

/**
 * Что человеку отправляли и чем это кончилось.
 *
 * Причина неудачи лежит у доставки, а не у уведомления: «Телеграм не
 * привязан», «тихие часы», отказ почтового сервера словами. Это и есть ответ
 * на «почему не пришло».
 */
function History({ rows }: { rows: Sent[] }) {
  if (!rows.length) {
    return (
      <p className="px-[15px] pb-2.5 text-[11.5px] text-ink-muted">
        Этому человеку платформа ещё ничего не ставила. Значит, дело не в
        рассылке — события до сервиса не доходят.
      </p>
    );
  }

  return (
    <ul className="space-y-1.5 bg-plane/40 px-[15px] py-2.5">
      {rows.map((one, index) => (
        <li key={`${one.at}-${index}`} className="text-[11.5px]">
          <span className="text-ink-secondary tabular-nums">
            {one.at.slice(0, 16).replace("T", " ")}
          </span>{" "}
          <span className="text-ink">{one.title || one.event}</span>
          {one.deliveries.map((way) => (
            <span key={way.channel} className="ml-2 text-ink-muted">
              {way.channel}: {way.status}
              {way.error && ` — ${way.error}`}
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}
