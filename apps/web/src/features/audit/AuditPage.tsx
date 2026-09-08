/**
 * Журнал действий: кто что сделал и когда.
 *
 * Открывают его в одном случае: что-то произошло, и надо понять, кто это
 * сделал. Поэтому порядок обратный по времени, поэтому отбор по человеку и по
 * дню стоит первым, и поэтому у каждой строки раскрывается то, что ушло на
 * сервер, — «перевёл лот» без причины перевода отвечает наполовину.
 *
 * Отказы выделены отдельным переключателем, а не поиском по коду ответа. «Кто
 * пытался и не смог» — первый вопрос, когда что-то пошло не так, а набирать
 * «403 или 404 или 500» руками никто не станет.
 *
 * Цвет кода ответа всегда со словом: при дальтонизме зелёное и красное
 * одинаково серые, а разница между «сделал» и «не дали» — та самая, ради
 * которой сюда и пришли.
 */

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { audit, type AuditEntry, type AuditQuery } from "@/api/audit";
import { PageHeader } from "@/shell/AppShell";
import {
  Button,
  Card as Panel,
  EmptyState,
  Input,
  Page,
  Search,
  Spinner,
  cx,
} from "@/ui";

/** Способы, которые меняют данные. Чтения в журнал не идут. */
const METHODS = ["", "POST", "PATCH", "PUT", "DELETE"];

export function AuditPage() {
  const [filters, setFilters] = useState<AuditQuery>({ page: 1 });
  const [open, setOpen] = useState<string | null>(null);

  const { data: people } = useQuery({
    queryKey: ["audit-people"],
    queryFn: audit.people,
    staleTime: 10 * 60 * 1000,
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit", filters],
    queryFn: () => audit.list(filters),
    // Прошлая страница остаётся на экране, пока грузится следующая: иначе
    // журнал мигает пустотой на каждое нажатие «дальше».
    placeholderData: keepPreviousData,
  });

  /** Любая правка отбора возвращает на первую страницу: иначе человек меняет
   *  день и видит пустоту, потому что остался на сорок второй. */
  const set = (patch: AuditQuery) =>
    setFilters((was) => ({ ...was, ...patch, page: 1 }));

  return (
    <>
      <PageHeader
        title="Журнал действий"
        subtitle="Каждое изменение: кто, когда, с какого адреса и что именно отправил"
        action={
          data ? (
            <span className="text-sm text-ink-muted tabular-nums">
              всего {data.total.toLocaleString("ru-KZ")}
            </span>
          ) : null
        }
      />

      <Page>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={filters.user_id ?? ""}
            onChange={(event) => set({ user_id: event.target.value })}
            className={cx(
              "h-9 rounded-[8px] border border-baseline bg-surface px-2.5 text-sm text-ink",
              "focus:border-series-1 focus:outline-none",
            )}
          >
            <option value="">Все сотрудники</option>
            {(people ?? []).map((person) => (
              <option key={person.id} value={person.id}>
                {person.name}
              </option>
            ))}
          </select>

          <select
            value={filters.method ?? ""}
            onChange={(event) => set({ method: event.target.value })}
            className={cx(
              "h-9 rounded-[8px] border border-baseline bg-surface px-2.5 text-sm text-ink",
              "focus:border-series-1 focus:outline-none",
            )}
          >
            {METHODS.map((one) => (
              <option key={one} value={one}>
                {one || "Любое действие"}
              </option>
            ))}
          </select>

          {/* Ширину задаёт обёртка, а не само поле: у `Input` стоит `w-full`,
              и рядом с ним `w-40` не выигрывает — порядок правил в готовом CSS
              решает, а не порядок классов в разметке. */}
          <span className="w-36">
            <Input
              type="date"
              value={(filters.since ?? "").slice(0, 10)}
              onChange={(event) =>
                set({
                  since: event.target.value
                    ? `${event.target.value}T00:00:00`
                    : "",
                })
              }
              title="С какого дня"
            />
          </span>
          <span className="w-36">
            <Input
              type="date"
              value={(filters.until ?? "").slice(0, 10)}
              onChange={(event) =>
                set({
                  until: event.target.value
                    ? `${event.target.value}T23:59:59`
                    : "",
                })
              }
              title="По какой день"
            />
          </span>

          <button
            type="button"
            onClick={() => set({ only_failed: !filters.only_failed })}
            className={cx(
              "h-9 rounded-[8px] border px-3 text-sm transition",
              filters.only_failed
                ? "border-critical bg-critical/10 font-medium text-critical"
                : "border-baseline text-ink hover:bg-plane",
            )}
          >
            Только отказы
          </button>

          <Search
            value={filters.search ?? ""}
            onChange={(next) => set({ search: next })}
            placeholder="Адрес, действие, содержимое"
          />

          {(filters.user_id ||
            filters.method ||
            filters.since ||
            filters.until ||
            filters.only_failed ||
            filters.search) && (
            <button
              type="button"
              onClick={() => setFilters({ page: 1 })}
              className="text-xs text-ink-muted transition hover:text-ink"
            >
              Снять отбор
            </button>
          )}
        </div>

        {isLoading && !data ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем журнал…" />
          </Panel>
        ) : error ? (
          <Panel>
            <EmptyState
              title="Журнал не открылся"
              description={
                error instanceof Error
                  ? error.message
                  : "Попробуйте обновить страницу"
              }
            />
          </Panel>
        ) : !data?.items.length ? (
          <Panel>
            <EmptyState
              title="Записей нет"
              description="Под этот отбор ничего не попало. Журнал ведётся с момента, когда его включили."
            />
          </Panel>
        ) : (
          <>
            <Panel className="overflow-hidden">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-plane text-left">
                    <Th className="w-36">Когда</Th>
                    <Th className="w-48">Кто</Th>
                    <Th>Действие</Th>
                    <Th className="w-24">Ответ</Th>
                    <Th className="w-32">Адрес</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <Row
                      key={row.id}
                      row={row}
                      open={open === row.id}
                      onToggle={() => setOpen(open === row.id ? null : row.id)}
                    />
                  ))}
                </tbody>
              </table>
            </Panel>

            {data.pages > 1 && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs text-ink-muted tabular-nums">
                  Страница {data.page} из {data.pages}
                </span>
                <span className="flex gap-2">
                  <Button
                    variant="secondary"
                    disabled={data.page <= 1}
                    onClick={() =>
                      setFilters((was) => ({
                        ...was,
                        page: (was.page ?? 1) - 1,
                      }))
                    }
                  >
                    ← Раньше
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={data.page >= data.pages}
                    onClick={() =>
                      setFilters((was) => ({
                        ...was,
                        page: (was.page ?? 1) + 1,
                      }))
                    }
                  >
                    Позже →
                  </Button>
                </span>
              </div>
            )}
          </>
        )}
      </Page>
    </>
  );
}

function Th({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      className={cx(
        "border-b border-hairline px-4 py-2 text-xs font-medium text-ink-muted",
        className,
      )}
    >
      {children}
    </th>
  );
}

/**
 * Строка журнала. Раскрывается в то, что ушло на сервер.
 *
 * Раскрывается, а не показывается сразу: тело запроса — это абзац JSON, и
 * пятьдесят абзацев подряд превращают журнал в стену, по которой не пробежать
 * глазами колонку «кто».
 */
function Row({
  row,
  open,
  onToggle,
}: {
  row: AuditEntry;
  open: boolean;
  onToggle: () => void;
}) {
  const failed = row.status >= 400;
  const body = Object.keys(row.payload).length > 0;

  return (
    <>
      <tr
        className={cx(
          "border-b border-hairline align-top transition",
          open ? "bg-plane" : "hover:bg-plane/50",
        )}
      >
        <td className="px-4 py-2 text-xs whitespace-nowrap text-ink-secondary tabular-nums">
          {moment(row.at)}
        </td>
        <td className="px-4 py-2">
          <span className="block truncate text-sm text-ink">
            {row.who || "без входа"}
          </span>
          {row.role && (
            <span className="block text-xs text-ink-muted">
              {ROLES[row.role] ?? row.role}
            </span>
          )}
        </td>
        <td className="px-4 py-2">
          <button
            type="button"
            onClick={onToggle}
            disabled={!body}
            className={cx(
              "text-left",
              body ? "hover:underline" : "cursor-default",
            )}
            title={body ? "Показать, что ушло на сервер" : undefined}
          >
            <span className="flex items-baseline gap-2">
              <Method method={row.method} />
              <span className="text-sm text-ink">{say(row)}</span>
              {body && (
                <span aria-hidden className="text-[10px] text-ink-muted">
                  {open ? "▾" : "▸"}
                </span>
              )}
            </span>
            <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-muted">
              {row.path}
              {row.target && ` · ${row.target}`}
            </span>
          </button>
        </td>
        <td className="px-4 py-2">
          {/* Цвет со словом: при дальтонизме зелёное и красное одинаково
              серые, а разница между «сделал» и «не дали» — та самая, ради
              которой журнал и открыли. */}
          <span
            className={cx(
              "text-xs font-medium whitespace-nowrap tabular-nums",
              failed ? "text-critical" : "text-good",
            )}
          >
            {row.status || "—"} {failed ? "отказ" : "ок"}
          </span>
          {row.duration_ms > 0 && (
            <span className="block text-[11px] text-ink-muted tabular-nums">
              {row.duration_ms} мс
            </span>
          )}
        </td>
        <td className="px-4 py-2 font-mono text-[11px] text-ink-muted">
          {row.ip}
        </td>
      </tr>

      {open && body && (
        <tr className="border-b border-hairline bg-plane">
          <td colSpan={5} className="px-4 pt-0 pb-3">
            <pre className="max-h-72 overflow-auto rounded-[8px] border border-hairline bg-surface p-3 text-xs leading-relaxed text-ink-secondary">
              {JSON.stringify(row.payload, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

function Method({ method }: { method: string }) {
  if (!method) {
    // Пусто — действие пришло не из браузера, а из прогона по расписанию.
    return <span className="text-[10px] text-ink-muted">прогон</span>;
  }
  return (
    <span
      className={cx(
        "rounded-[4px] px-1 py-0.5 font-mono text-[10px] font-semibold",
        method === "DELETE"
          ? "bg-critical/10 text-critical"
          : method === "POST"
            ? "bg-series-3/15 text-ink"
            : "bg-series-1/10 text-series-1",
      )}
    >
      {method}
    </span>
  );
}

const ROLES: Record<string, string> = {
  admin: "Администратор",
  analyst: "Тендерщик",
  buyer: "Закупщик",
  manager: "Менеджер",
  lawyer: "Юрист",
  technologist: "Технолог",
  assembler: "Сборщик",
  viewer: "Наблюдатель",
};

/**
 * Действие словами.
 *
 * Из образца пути, а не из выдуманного справочника на сотню строк: справочник
 * разойдётся с маршрутами на первой же правке, и в журнале появится «неизвестно
 * что» ровно у нового раздела. Здесь читается сам путь — он и есть правда.
 */
function say(row: AuditEntry): string {
  const known = ACTIONS[row.action];
  if (known) return known;
  const tail = row.action.replace(/^[A-Z]+\s/, "").replace(/^\/api\//, "");
  return tail || row.action;
}

/** Частые действия — своими словами. Остальные читаются по пути. */
const ACTIONS: Record<string, string> = {
  "POST /api/auth/login": "Вошёл в платформу",
  "POST /api/auth/logout": "Вышел",
  "POST /api/auth/password": "Сменил пароль",
  "PATCH /api/auth/me": "Изменил свои данные",
  "POST /api/auth/reset/ask": "Запросил код смены пароля",
  "POST /api/auth/reset/confirm": "Сменил пароль по коду",
  "POST /api/cards": "Взял лот в работу",
  "POST /api/cards/{card_id}/move": "Перевёл лот",
  "POST /api/cards/{card_id}/tasks": "Завёл задачу",
  "POST /api/cards/tasks/{task_id}/take": "Взял задачу",
  "POST /api/cards/tasks/{task_id}/close": "Закрыл задачу",
  "POST /api/cards/{card_id}/approve": "Подписал согласование",
  "POST /api/cards/{card_id}/assign": "Назначил ответственного",
  "POST /api/remarks/{remark_id}/move": "Перевёл обсуждение",
  "POST /api/remarks/{remark_id}/resolve": "Записал итог обсуждения",
  "POST /api/goszakup/fetch": "Забрал закупку по номеру",
  "POST /api/goszakup/sync": "Обновил лоты с портала",
  "DELETE /api/goszakup/lots": "Стёр лоты площадки",
};

/** Когда: день и время до секунды. Секунды нужны — события идут пачками. */
function moment(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? "—"
    : at.toLocaleString("ru-KZ", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}
