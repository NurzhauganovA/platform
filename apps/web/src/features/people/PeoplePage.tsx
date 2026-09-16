/**
 * Сотрудники и роли.
 *
 * Только администратору. За экраном почты всех сотрудников, их роли и право
 * выдать себе любое из прав; вопрос «кто может видеть себестоимость» задаёт не
 * тот, кому её не показывают.
 *
 * Две вкладки, а не два раздела меню. Работа одна: человека заводят и сразу
 * выбирают ему роль, а не найдя подходящей — заводят роль и возвращаются. Два
 * пункта меню означали бы переход туда-обратно посреди одного дела.
 *
 * Роль показывается набором прав, а не одним словом. «Тендерщик» ничего не
 * говорит тому, кто выдаёт доступ впервые: он должен видеть, что вместе с
 * ролью уходит себестоимость.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  peopleApi,
  type Permission,
  type Person,
  type WorkRole,
} from "@/api/people";
import { ApiError } from "@/api/client";
import { PageHeader } from "@/shell/AppShell";
import {
  Button,
  Card as Panel,
  EmptyState,
  Input,
  Page,
  Spinner,
  Tabs,
  cx,
} from "@/ui";
import { stamp } from "@/features/cards/kit";

type Tab = "people" | "roles";

const TABS: { key: Tab; title: string }[] = [
  { key: "people", title: "Сотрудники" },
  { key: "roles", title: "Роли" },
];

export function PeoplePage() {
  const [tab, setTab] = useState<Tab>("people");

  const { data: people, isLoading } = useQuery({
    queryKey: ["people", "list"],
    queryFn: peopleApi.list,
  });
  const { data: roles } = useQuery({
    queryKey: ["people", "roles"],
    queryFn: peopleApi.roles,
  });
  const { data: permissions } = useQuery({
    queryKey: ["people", "permissions"],
    queryFn: peopleApi.permissions,
    staleTime: 60 * 60_000,
  });

  const counts: Record<Tab, number> = {
    people: people?.filter((one) => one.is_active).length ?? 0,
    roles: roles?.length ?? 0,
  };

  return (
    <>
      <PageHeader
        title="Сотрудники"
        subtitle="Кого пускаем в платформу и что ему можно"
      />
      <Page>
        <Tabs tabs={TABS} value={tab} counts={counts} onChange={setTab} />

        {isLoading ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем список…" />
          </Panel>
        ) : tab === "people" ? (
          <People people={people ?? []} roles={roles ?? []} />
        ) : (
          <Roles roles={roles ?? []} permissions={permissions ?? []} />
        )}
      </Page>
    </>
  );
}

/** Список людей: кто заведён, с какой ролью и входит ли вообще. */
function People({ people, roles }: { people: Person[]; roles: WorkRole[] }) {
  const cache = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [trouble, setTrouble] = useState("");

  const refresh = () => {
    setTrouble("");
    void cache.invalidateQueries({ queryKey: ["people"] });
  };
  const fail = (error: unknown) =>
    setTrouble(error instanceof ApiError ? error.message : "Не получилось");

  const save = useMutation({
    mutationFn: (input: {
      id: string;
      body: { role?: string; is_active?: boolean; password?: string };
    }) => peopleApi.save(input.id, input.body),
    onSuccess: refresh,
    onError: fail,
  });
  const purge = useMutation({
    mutationFn: (id: string) => peopleApi.purge(id),
    onSuccess: refresh,
    onError: fail,
  });

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2.5">
        <Button variant="primary" onClick={() => setAdding((open) => !open)}>
          {adding ? "Не заводить" : "Завести сотрудника"}
        </Button>
        <span className="text-[12.5px] text-ink-muted">
          Выключенный не входит и не получает уведомлений. Удалённый исчезает из
          списка, но подписи и лента событий остаются с его именем
        </span>
      </div>

      {trouble && (
        <p
          role="alert"
          className="rounded-[10px] border border-critical/40 bg-critical/10 px-[15px] py-2.5 text-[12.5px] text-ink"
        >
          {trouble}
        </p>
      )}

      {adding && (
        <NewPerson
          roles={roles}
          onDone={() => {
            setAdding(false);
            refresh();
          }}
          onFail={fail}
        />
      )}

      {people.length === 0 ? (
        <Panel>
          <EmptyState
            title="Пока никого"
            description="Первого сотрудника заводят командой make user, остальных — отсюда."
          />
        </Panel>
      ) : (
        <Panel className="overflow-hidden">
          <ul>
            {people.map((one) => (
              <Row
                key={one.id}
                person={one}
                roles={roles}
                busy={save.isPending}
                onRole={(role) => save.mutate({ id: one.id, body: { role } })}
                onActive={(is_active) =>
                  save.mutate({ id: one.id, body: { is_active } })
                }
                onPassword={(password) =>
                  save.mutate({ id: one.id, body: { password } })
                }
                onPurge={() => purge.mutate(one.id)}
              />
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

function Row({
  person,
  roles,
  busy,
  onRole,
  onActive,
  onPassword,
  onPurge,
}: {
  person: Person;
  roles: WorkRole[];
  busy: boolean;
  onRole: (role: string) => void;
  onActive: (is_active: boolean) => void;
  onPassword: (password: string) => void;
  onPurge: () => void;
}) {
  const [fresh, setFresh] = useState("");
  const [asking, setAsking] = useState(false);
  const [purging, setPurging] = useState(false);

  return (
    <li className="border-b border-hairline/70 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-[15px] py-2.5">
        <span className="min-w-0 flex-1">
          <span
            className={cx(
              "block truncate text-[13px] font-medium",
              person.is_active ? "text-ink" : "text-ink-muted line-through",
            )}
          >
            {person.full_name || person.email}
          </span>
          <span className="block truncate text-[11.5px] text-ink-muted">
            {person.email}
            {person.last_login_at &&
              ` · заходил ${stamp(person.last_login_at)}`}
          </span>
        </span>

        {/* Замок виден отдельно: человек звонит и говорит «не пускает», а по
            списку это иначе не отличить от выключенного. */}
        {person.locked && (
          <span className="shrink-0 rounded-[6px] bg-warning/15 px-1.5 py-0.5 text-[11px] text-ink">
            вход заперт
          </span>
        )}

        <select
          value={person.role}
          disabled={busy}
          onChange={(event) => onRole(event.target.value)}
          aria-label="Роль"
          className={cx(
            "shrink-0 rounded-[7px] border border-hairline bg-surface px-2 py-1",
            "text-[12.5px] text-ink focus:border-series-1 focus:outline-none",
          )}
        >
          {roles.map((role) => (
            <option key={role.key} value={role.key}>
              {role.title}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => setAsking((open) => !open)}
          className="shrink-0 rounded-[6px] px-2 py-0.5 text-[11.5px] text-ink-muted transition hover:bg-plane hover:text-ink"
        >
          Сменить пароль
        </button>

        <button
          type="button"
          disabled={busy}
          onClick={() => onActive(!person.is_active)}
          className={cx(
            "shrink-0 rounded-[6px] px-2 py-0.5 text-[11.5px] transition disabled:opacity-45",
            person.is_active
              ? "text-ink-muted hover:bg-critical/10 hover:text-critical"
              : "font-medium text-series-1 hover:underline",
          )}
        >
          {person.is_active ? "Выключить" : "Включить"}
        </button>

        <button
          type="button"
          disabled={busy}
          onClick={() => setPurging((open) => !open)}
          className="shrink-0 rounded-[6px] px-2 py-0.5 text-[11.5px] text-ink-muted transition hover:bg-critical/10 hover:text-critical disabled:opacity-45"
        >
          Удалить
        </button>
      </div>

      {purging && (
        /* Спрашиваем до, а не сообщаем после, и называем ровно то, что
           произойдёт. «Удалить сотрудника?» человек подтверждает не читая, а
           «его подписи останутся, лоты станут ничьими» — это уже решение. */
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline/70 bg-critical/5 px-[15px] py-2.5">
          <span className="min-w-0 flex-1 text-[12px] text-ink">
            Удалить запись {person.email}? Подписи под участием и лента событий
            останутся с его именем; лоты, которые он вёл, станут ничьими. Войти
            он больше не сможет — вместе с записью уйдут сессии и коды
            восстановления.
          </span>
          <Button variant="ghost" onClick={() => setPurging(false)}>
            Отмена
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              setPurging(false);
              onPurge();
            }}
          >
            Удалить навсегда
          </Button>
        </div>
      )}

      {asking && (
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline/70 bg-plane/40 px-[15px] py-2.5">
          <Input
            value={fresh}
            type="password"
            autoFocus
            placeholder="Новый пароль"
            onChange={(event) => setFresh(event.target.value)}
            className="w-64"
          />
          <Button
            variant="primary"
            disabled={!fresh.trim() || busy}
            onClick={() => {
              onPassword(fresh);
              setFresh("");
              setAsking(false);
            }}
          >
            Сменить
          </Button>
          {/* Смена гасит прежние входы: иначе тот, кто увёл пароль, сидит в
              платформе до конца срока сессии. */}
          <span className="text-[11.5px] text-ink-muted">
            прежние входы этого человека погаснут
          </span>
        </div>
      )}
    </li>
  );
}

function NewPerson({
  roles,
  onDone,
  onFail,
}: {
  roles: WorkRole[];
  onDone: () => void;
  onFail: (error: unknown) => void;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("viewer");
  const [password, setPassword] = useState("");

  const add = useMutation({
    mutationFn: () => peopleApi.add({ email, full_name: name, role, password }),
    onSuccess: onDone,
    onError: onFail,
  });

  return (
    <Panel className="flex flex-wrap items-end gap-2.5 px-[15px] py-3">
      <Field label="Почта">
        <Input
          value={email}
          autoFocus
          placeholder="name@fintend.kz"
          onChange={(event) => setEmail(event.target.value)}
          className="w-56"
        />
      </Field>
      <Field label="Имя и фамилия">
        <Input
          value={name}
          placeholder="Нуржауганов Анварбек"
          onChange={(event) => setName(event.target.value)}
          className="w-56"
        />
      </Field>
      <Field label="Роль">
        <select
          value={role}
          onChange={(event) => setRole(event.target.value)}
          className={cx(
            "h-[34px] rounded-[8px] border border-hairline bg-surface px-2",
            "text-[13px] text-ink focus:border-series-1 focus:outline-none",
          )}
        >
          {roles.map((one) => (
            <option key={one.key} value={one.key}>
              {one.title}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Пароль">
        <Input
          value={password}
          type="password"
          onChange={(event) => setPassword(event.target.value)}
          className="w-56"
        />
      </Field>
      <Button
        variant="primary"
        disabled={!email.trim() || !password.trim() || add.isPending}
        onClick={() => add.mutate()}
      >
        {add.isPending ? "Заводим…" : "Завести"}
      </Button>
    </Panel>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11.5px] text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

/** Роли и их права: что уходит вместе с ролью. */
function Roles({
  roles,
  permissions,
}: {
  roles: WorkRole[];
  permissions: Permission[];
}) {
  const cache = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [trouble, setTrouble] = useState("");

  const refresh = () => {
    setTrouble("");
    void cache.invalidateQueries({ queryKey: ["people"] });
  };
  const fail = (error: unknown) =>
    setTrouble(error instanceof ApiError ? error.message : "Не получилось");

  const drop = useMutation({
    mutationFn: (input: { key: string; force: boolean }) =>
      peopleApi.dropRole(input.key, input.force),
    onSuccess: refresh,
    onError: fail,
  });

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2.5">
        <Button variant="primary" onClick={() => setAdding((open) => !open)}>
          {adding ? "Не заводить" : "Завести роль"}
        </Button>
        <span className="text-[12.5px] text-ink-muted">
          Встроенные роли не правятся: на их правах держатся проверки по всей
          платформе
        </span>
      </div>

      {trouble && (
        <p
          role="alert"
          className="rounded-[10px] border border-critical/40 bg-critical/10 px-[15px] py-2.5 text-[12.5px] text-ink"
        >
          {trouble}
        </p>
      )}

      {adding && (
        <NewRole
          permissions={permissions}
          onDone={() => {
            setAdding(false);
            refresh();
          }}
          onFail={fail}
        />
      )}

      <Panel className="overflow-hidden">
        <ul>
          {roles.map((role) => (
            <RoleRow
              key={role.key}
              role={role}
              permissions={permissions}
              busy={drop.isPending}
              onDone={refresh}
              onFail={fail}
              onDrop={(force) => drop.mutate({ key: role.key, force })}
            />
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function RoleRow({
  role,
  permissions,
  busy,
  onDone,
  onFail,
  onDrop,
}: {
  role: WorkRole;
  permissions: Permission[];
  busy: boolean;
  onDone: () => void;
  onFail: (error: unknown) => void;
  onDrop: (force: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [picked, setPicked] = useState<string[]>(role.permissions);

  // Список прав приходит с сервера и меняется после сохранения — подхватываем
  // его, иначе галочки остаются теми, какими были при первом раскрытии.
  useEffect(() => setPicked(role.permissions), [role.permissions]);

  const save = useMutation({
    mutationFn: () => peopleApi.saveRole(role.key, { permissions: picked }),
    onSuccess: () => {
      setOpen(false);
      onDone();
    },
    onError: onFail,
  });
  const reset = useMutation({
    mutationFn: () => peopleApi.resetRole(role.key),
    onSuccess: () => {
      setOpen(false);
      onDone();
    },
    onError: onFail,
  });

  return (
    <li className="border-b border-hairline/70 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-[15px] py-2.5">
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          className="min-w-0 flex-1 text-left"
        >
          <span className="flex items-baseline gap-2">
            <span className="truncate text-[13px] font-medium text-ink">
              {role.title}
            </span>
            <span className="shrink-0 font-mono text-[11px] text-ink-muted">
              {role.key}
            </span>
            {role.built_in && (
              <span className="shrink-0 rounded-[6px] bg-plane px-1.5 py-0.5 text-[11px] text-ink-muted">
                встроенная
              </span>
            )}
            {role.changed && (
              <span
                title="Права правили руками: заводские можно вернуть"
                className="shrink-0 rounded-[6px] bg-warning/15 px-1.5 py-0.5 text-[11px] text-ink"
              >
                правлена
              </span>
            )}
          </span>
          <span className="block truncate text-[11.5px] text-ink-muted">
            {role.about || "без пояснения"}
          </span>
        </button>

        <span className="shrink-0 text-[11.5px] text-ink-muted tabular-nums">
          прав {role.permissions.length} · людей {role.people}
        </span>

        {!role.built_in && (
          <button
            type="button"
            disabled={busy}
            onClick={() => (role.people ? setAsking(true) : onDrop(false))}
            title="Убрать роль"
            className="shrink-0 rounded-[6px] px-2 py-0.5 text-[11.5px] text-ink-muted transition hover:bg-critical/10 hover:text-critical disabled:opacity-45"
          >
            Убрать
          </button>
        )}
      </div>

      {asking && (
        /* Занятую роль убираем только после прямого ответа: люди на ней
           останутся в платформе и станут наблюдателями — придут утром и не
           найдут своих разделов. */
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline/70 bg-critical/5 px-[15px] py-2.5">
          <span className="min-w-0 flex-1 text-[12px] text-ink">
            Роль носят {role.people} чел. Убрать вместе с ней? Они останутся в
            платформе, но станут наблюдателями — списки и карточки закроются.
          </span>
          <Button variant="ghost" onClick={() => setAsking(false)}>
            Отмена
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              setAsking(false);
              onDrop(true);
            }}
          >
            Убрать и снять с людей
          </Button>
        </div>
      )}

      {open && (
        <div className="border-t border-hairline/70 bg-plane/40 px-[15px] py-2.5">
          {/* Галочки живые и у встроенных ролей. «Тендерщик без аналитики» —
              это настройка, а не новая роль: заводить рядом копию из десяти
              галочек ради снятия одной значит держать два списка и однажды
              поправить только один. Заводские права при этом остаются в коде,
              и кнопка рядом возвращает к ним. */}
          <Boxes
            permissions={permissions}
            picked={picked}
            onChange={setPicked}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Сохраняем…" : "Сохранить права"}
            </Button>
            {role.built_in && role.changed && (
              <Button
                variant="secondary"
                disabled={reset.isPending}
                onClick={() => reset.mutate()}
              >
                {reset.isPending ? "Возвращаем…" : "Вернуть заводские"}
              </Button>
            )}
            <span className="text-[11.5px] text-ink-muted">
              подействует при следующем входе этих людей
            </span>
          </div>
        </div>
      )}
    </li>
  );
}

function NewRole({
  permissions,
  onDone,
  onFail,
}: {
  permissions: Permission[];
  onDone: () => void;
  onFail: (error: unknown) => void;
}) {
  const [key, setKey] = useState("");
  const [title, setTitle] = useState("");
  const [about, setAbout] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const add = useMutation({
    mutationFn: () =>
      peopleApi.addRole({
        key,
        title,
        description: about,
        permissions: picked,
      }),
    onSuccess: onDone,
    onError: onFail,
  });

  return (
    <Panel className="px-[15px] py-3">
      <div className="flex flex-wrap items-end gap-2.5">
        <Field label="Название">
          <Input
            value={title}
            autoFocus
            placeholder="Снабженец без цен"
            onChange={(event) => setTitle(event.target.value)}
            className="w-56"
          />
        </Field>
        <Field label="Ключ (латиницей)">
          <Input
            value={key}
            placeholder="supply_no_money"
            onChange={(event) =>
              setKey(
                event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""),
              )
            }
            className="w-48"
          />
        </Field>
        <Field label="Пояснение">
          <Input
            value={about}
            placeholder="Ищет товар, цен не видит"
            onChange={(event) => setAbout(event.target.value)}
            className="w-72"
          />
        </Field>
      </div>

      <div className="mt-3">
        <Boxes permissions={permissions} picked={picked} onChange={setPicked} />
      </div>

      <div className="mt-3">
        <Button
          variant="primary"
          disabled={!key.trim() || !title.trim() || add.isPending}
          onClick={() => add.mutate()}
        >
          {add.isPending ? "Заводим…" : "Завести роль"}
        </Button>
      </div>
    </Panel>
  );
}

/**
 * Права галочками, по группам.
 *
 * Списком, а не выпадающим выбором: их четыре десятка, и выдающий доступ
 * должен видеть все разом — в том числе те, которые он не ставит. Пояснение у
 * каждого своё: `money` без слов означает, что выдавать будут наугад.
 *
 * Группы нужны с того момента, как прав стало больше десятка. «Страницы» —
 * куда человек может зайти, ими управляется меню; «Лоты» и «Работа» — что он
 * может сделать; «Подписи» — пять однотипных; «Платформа» — управление
 * доступами. Без групп это сорок галочек подряд, по которым ищут глазами.
 *
 * У каждой группы «выбрать все» и «снять»: роль обычно собирают целыми
 * областями — «все страницы работы, ничего из площадок», — и сорок нажатий
 * вместо двух это то, из-за чего роли не заводят вообще.
 */
function Boxes({
  permissions,
  picked,
  onChange,
}: {
  permissions: Permission[];
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  const groups = GROUPS.map((group) => ({
    ...group,
    items: permissions.filter((one) => group.match(one.key)),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="space-y-3">
      {groups.map((group) => {
        const keys = group.items.map((one) => one.key);
        const all = keys.every((key) => picked.includes(key));

        return (
          <div key={group.title}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className="text-[11.5px] font-semibold tracking-[0.02em] text-ink-secondary uppercase">
                {group.title}
              </span>
              <span className="text-[11px] text-ink-muted tabular-nums">
                {keys.filter((key) => picked.includes(key)).length} из{" "}
                {keys.length}
              </span>
              <button
                type="button"
                onClick={() =>
                  onChange(
                    all
                      ? picked.filter((key) => !keys.includes(key))
                      : [...new Set([...picked, ...keys])],
                  )
                }
                className="rounded-[6px] px-1.5 py-0.5 text-[11px] text-series-1 transition hover:underline"
              >
                {all ? "снять все" : "выбрать все"}
              </button>
            </div>

            <ul className="grid gap-x-5 gap-y-1.5 sm:grid-cols-2">
              {group.items.map((one) => (
                <li key={one.key}>
                  <label className="flex cursor-pointer items-start gap-2">
                    <input
                      type="checkbox"
                      checked={picked.includes(one.key)}
                      onChange={(event) =>
                        onChange(
                          event.target.checked
                            ? [...picked, one.key]
                            : picked.filter((item) => item !== one.key),
                        )
                      }
                      className="mt-0.5 h-[15px] w-[15px] shrink-0 accent-[var(--color-series-1)]"
                    />
                    <span className="min-w-0">
                      <span className="block text-[12.5px] text-ink">
                        {one.title}
                      </span>
                      <span className="block text-[11.5px] text-ink-muted">
                        {one.about}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Как права раскладываются по группам.
 *
 * По ключу, а не по отдельному полю в ответе: ключ и так говорит об области
 * («page.», «lot.», «sign.»), и второй источник этой же разметки разошёлся бы
 * с первым на первом же добавленном праве.
 */
const GROUPS: { title: string; match: (key: string) => boolean }[] = [
  { title: "Страницы", match: (key) => key.startsWith("page.") },
  { title: "Лоты", match: (key) => key.startsWith("lot.") },
  {
    title: "Работа с лотом",
    match: (key) =>
      ["crm", "tasks", "files", "move", "decide"].includes(key) ||
      key.startsWith("sheet.") ||
      key.startsWith("remark."),
  },
  { title: "Подписи", match: (key) => key.startsWith("sign.") },
  {
    title: "Данные",
    match: (key) => ["money", "read", "sourcing", "remarks"].includes(key),
  },
  { title: "Платформа", match: (key) => key === "admin" },
];
