/**
 * Свой профиль: кто я, чем вхожу, куда мне писать и как это выглядит.
 *
 * Четыре блока на одной странице, а не четыре страницы. Сюда заходят редко и с
 * разными поводами — сменить фамилию, привязать Телеграм, переключить тему,
 * поменять пароль, — и общее у них одно: это про меня, а не про лоты. Искать
 * их по разделам значило бы держать в голове, где что лежит.
 *
 * Всё меняет сам сотрудник. Ждать администратора ради смены фамилии — это день
 * в лучшем случае, а пароль, который неудобно сменить, не меняют вовсе.
 */

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { auth, type Channels, type Me } from "@/api/tender";
import { ApiError } from "@/api/client";
import { PageHeader } from "@/shell/AppShell";
import { Button, Card as Panel, Input, Page, Spinner, cx } from "@/ui";
import { THEMES, useTheme } from "./theme";

export function ProfilePage({ me }: { me: Me }) {
  return (
    <>
      <PageHeader
        title="Профиль"
        subtitle="Учётная запись, уведомления и вид платформы"
      />
      <Page>
        <div className="grid gap-3 lg:grid-cols-2">
          <Who me={me} />
          <Look />
          <Where />
          <Secret />
        </div>
      </Page>
    </>
  );
}

/** Имя и почта. Почтой входят — она же адрес для кодов. */
function Who({ me }: { me: Me }) {
  const cache = useQueryClient();
  const [name, setName] = useState(me.full_name);
  const [mail, setMail] = useState(me.email);
  const [saved, setSaved] = useState(false);
  const [trouble, setTrouble] = useState("");

  const save = useMutation({
    mutationFn: () => auth.rename(name, mail),
    onSuccess: (fresh) => {
      setTrouble("");
      setSaved(true);
      cache.setQueryData(["me"], fresh);
      window.setTimeout(() => setSaved(false), 2500);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не сохранилось"),
  });

  const changed = name !== me.full_name || mail !== me.email;

  return (
    <Panel title="Кто я">
      <div className="space-y-3 px-4 py-3">
        <Field label="Имя и фамилия">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field
          label="Рабочая почта"
          hint="Ею входят. На неё же приходит код привязки Телеграма и код смены пароля."
        >
          <Input
            type="email"
            value={mail}
            onChange={(e) => setMail(e.target.value)}
          />
        </Field>
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            disabled={!changed || save.isPending}
          >
            {save.isPending ? "Сохраняем…" : "Сохранить"}
          </Button>
          {saved && <span className="text-xs text-good">✓ сохранено</span>}
        </div>
        {trouble && <p className="text-sm text-critical">{trouble}</p>}
      </div>
    </Panel>
  );
}

/** Тема. Правила цвета живут в `tokens.css`, здесь только выбор. */
function Look() {
  const [theme, setTheme] = useTheme();

  return (
    <Panel title="Вид">
      <div className="space-y-2 px-4 py-3">
        <p className="text-xs text-ink-muted">
          Цвет платформы. Выбор помнится на этом устройстве: за одним
          компьютером в отделе сидят по очереди, и тема — про глаза и про
          монитор, а не про то, кто вошёл.
        </p>
        <div className="flex flex-wrap gap-2">
          {THEMES.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTheme(item.key)}
              className={cx(
                "rounded-[9px] border px-3 py-2 text-sm transition",
                "focus-visible:outline focus-visible:outline-2",
                "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
                theme === item.key
                  ? "border-series-1 bg-series-1/10 font-medium text-series-1"
                  : "border-baseline text-ink hover:bg-plane",
              )}
            >
              {item.title}
            </button>
          ))}
        </div>
      </div>
    </Panel>
  );
}

/**
 * Каналы уведомлений.
 *
 * Выбирает сам сотрудник: один читает Телеграм и не открывает почту неделями,
 * другой наоборот. Решать это за них значит рассылать в пустоту.
 *
 * Телеграм привязывается в самом боте, а не здесь: код уходит на рабочую
 * почту, и назвать его надо там же, где сидит чат. Отсюда — ссылка на бота и
 * состояние привязки.
 */
function Where() {
  const cache = useQueryClient();
  const [trouble, setTrouble] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["channels"],
    queryFn: auth.channels,
    retry: false,
  });

  const set = useMutation({
    mutationFn: (body: {
      telegram_enabled?: boolean;
      email_enabled?: boolean;
    }) => auth.setChannels(body),
    onSuccess: (fresh) => {
      setTrouble("");
      cache.setQueryData(["channels"], fresh);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const unlink = useMutation({
    mutationFn: () => auth.unlinkTelegram(),
    onSuccess: (fresh) => cache.setQueryData(["channels"], fresh),
  });

  if (isLoading) {
    return (
      <Panel title="Уведомления">
        <div className="px-4 py-4">
          <Spinner label="Читаем настройки…" />
        </div>
      </Panel>
    );
  }

  const now: Channels | undefined = data;

  if (!now?.ready) {
    return (
      <Panel title="Уведомления">
        <p className="px-4 py-4 text-sm text-ink-muted">
          Сервис уведомлений сейчас недоступен. Работе это не мешает: лоты,
          задачи и согласование на месте — не приходят только сообщения.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title="Уведомления">
      <div className="space-y-3 px-4 py-3">
        <Switchable
          title="Телеграм"
          note={
            now.telegram_linked
              ? "Чат привязан — сообщения приходят сюда."
              : "Чат не привязан. Напишите боту рабочую почту, он пришлёт на неё код."
          }
          on={now.telegram_enabled && now.telegram_linked}
          disabled={!now.telegram_linked || set.isPending}
          onChange={(on) => set.mutate({ telegram_enabled: on })}
        />

        {!now.telegram_linked && now.bot_username && (
          <a
            href={`https://t.me/${now.bot_username}`}
            target="_blank"
            rel="noreferrer"
            className="inline-block text-sm text-series-1 hover:underline"
          >
            Написать боту @{now.bot_username} →
          </a>
        )}
        {now.telegram_linked && (
          <button
            type="button"
            onClick={() => unlink.mutate()}
            disabled={unlink.isPending}
            className="text-xs text-ink-muted transition hover:text-critical"
          >
            {unlink.isPending ? "Отвязываем…" : "Отвязать Телеграм"}
          </button>
        )}

        <Switchable
          title="Почта"
          note="Запасной путь. Пока Телеграм не привязан, всё идёт письмами."
          on={now.email_enabled}
          disabled={set.isPending}
          onChange={(on) => set.mutate({ email_enabled: on })}
        />

        {/* Оба выключены — это тишина, и сказать об этом надо прямо: человек
            выключает второй канал, не заметив, что первый уже выключен, а
            потом не понимает, почему не узнал о сроке. */}
        {!now.email_enabled &&
          !(now.telegram_enabled && now.telegram_linked) && (
            <p className="rounded-[8px] border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-ink">
              Оба канала выключены — уведомления не придут никак. Сроки и задачи
              останутся видны только на экране.
            </p>
          )}

        {trouble && <p className="text-sm text-critical">{trouble}</p>}
      </div>
    </Panel>
  );
}

/** Пароль. Меняется по старому и гасит все сессии, включая эту. */
function Secret() {
  const [current, setCurrent] = useState("");
  const [fresh, setFresh] = useState("");
  const [again, setAgain] = useState("");
  const [trouble, setTrouble] = useState("");

  const change = useMutation({
    mutationFn: () => auth.password(current, fresh),
    // Все сессии гаснут, включая эту: пароль меняют в том числе потому, что
    // его подсмотрели, и оставленная открытой вкладка отменяла бы смену.
    onSuccess: () => window.location.assign("/login"),
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const ready =
    current.length > 0 &&
    fresh.length > 0 &&
    fresh === again &&
    !change.isPending;

  return (
    <Panel title="Пароль">
      <div className="space-y-3 px-4 py-3">
        <Field label="Текущий пароль">
          <Input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
        </Field>
        <Field label="Новый пароль">
          <Input
            type="password"
            value={fresh}
            onChange={(e) => setFresh(e.target.value)}
            autoComplete="new-password"
          />
        </Field>
        <Field
          label="Ещё раз"
          hint="После смены вход будет заново — на всех устройствах."
        >
          <Input
            type="password"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
            autoComplete="new-password"
          />
        </Field>
        {again.length > 0 && fresh !== again && (
          <p className="text-xs text-critical">Пароли не совпадают</p>
        )}
        <Button
          variant="primary"
          onClick={() => change.mutate()}
          disabled={!ready}
        >
          {change.isPending ? "Меняем…" : "Сменить пароль"}
        </Button>
        {trouble && <p className="text-sm text-critical">{trouble}</p>}
      </div>
    </Panel>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-ink-muted">{label}</span>
      {children}
      {hint && (
        <span className="mt-1 block text-xs text-ink-muted">{hint}</span>
      )}
    </label>
  );
}

/**
 * Переключатель канала.
 *
 * Состояние словом рядом с положением: включённое от выключенного отличается
 * положением кружка и цветом подложки, а при дальтонизме — только положением,
 * и это половина признака.
 */
function Switchable({
  title,
  note,
  on,
  disabled,
  onChange,
}: {
  title: string;
  note: string;
  on: boolean;
  disabled?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={title}
        disabled={disabled}
        onClick={() => onChange(!on)}
        className={cx(
          "mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-series-1",
          "disabled:cursor-not-allowed disabled:opacity-45",
          on ? "bg-series-1" : "bg-baseline",
        )}
      >
        <span
          className={cx(
            "h-4 w-4 rounded-full bg-surface transition-transform",
            on && "translate-x-4",
          )}
        />
      </button>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="text-sm font-medium text-ink">{title}</span>
          <span className="text-xs text-ink-muted">
            {on ? "включено" : "выключено"}
          </span>
        </span>
        <span className="mt-0.5 block text-xs text-ink-muted">{note}</span>
      </span>
    </div>
  );
}
