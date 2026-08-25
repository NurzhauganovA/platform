/**
 * Лот в работе: один экран на два отдела.
 *
 * Экран один, а показывает он разное — и это не ветвление ради экономии.
 * Отделы смотрят на один и тот же лот, и расхождение между «моей страницей» и
 * «его страницей» в двух файлах кончается тем, что позиция есть у одного и
 * нет у другого.
 *
 * Разбор видит деньги и подтверждает поставщиков. Снабжение видит только
 * позиции, их документы и «где купить»: суммы ему не приходят вовсе — не
 * скрыты вёрсткой, а отсутствуют в ответе.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import type { Role } from "@/api/tender";
import {
  worksApi,
  type Work,
  type WorkOption,
  type WorkPosition,
} from "@/api/worklist";
import { PageHeader } from "@/shell/AppShell";
import { Button, Card, Spinner, cx, money } from "@/ui";
import { STAGES } from "./WorksPage";
import { OptionForm } from "./OptionForm";

export function WorkPage({ role }: { role: Role }) {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["works", id],
    queryFn: () => worksApi.one(id),
  });

  const refresh = (work: Work) => client.setQueryData(["works", id], work);
  // Отдел разбора — тендерщик; снабжение — закупщик. Третьего понятия ролей
  // не заводим: оно означало бы и третье место, где их надо согласовать.
  const analysis = role === "analyst" || role === "admin";

  if (isLoading) return <Spinner label="Открываем лот…" />;
  if (isError || !data)
    return (
      <div className="px-8 py-6">
        <Card className="px-5 py-4 text-sm text-ink-secondary">
          {error instanceof Error ? error.message : "Лот не открылся"}
        </Card>
      </div>
    );

  const stage = STAGES[data.stage];
  const мой = analysis ? data.stage !== "supply" : data.stage === "supply";

  return (
    <>
      <PageHeader
        title={`${data.code} · ${data.title}`}
        subtitle={data.customer}
        action={
          <Link
            to="/tender/works"
            className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
          >
            ← Ко всем работам
          </Link>
        }
      />

      <div className="space-y-4 px-8 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={cx(
              "rounded-full px-2.5 py-1 text-xs font-medium",
              stage.tone,
            )}
          >
            {stage.title} · {stage.hint}
          </span>
          {!мой && (
            // Чужой ход — не «доступ запрещён», а «сейчас не ваша очередь».
            // Разница в том, ждать или звонить администратору.
            <span className="text-xs text-ink-muted">
              Пока лот у другого отдела, править его нельзя — можно смотреть
            </span>
          )}
        </div>

        {analysis && <Money work={data} />}
        <Notes work={data} />

        {data.positions.map((position, index) => (
          <PositionCard
            key={position.id}
            work={data}
            position={position}
            number={index + 1}
            analysis={analysis}
            editable={мой}
            onDone={refresh}
          />
        ))}

        {мой && <HandOver work={data} analysis={analysis} onDone={refresh} />}
      </div>
    </>
  );
}

/** Деньги по лоту — только отделу разбора. */
function Money({ work }: { work: Work }) {
  const прибыль =
    work.total !== null && work.cost !== null ? work.total - work.cost : null;
  const неполно = work.priced < work.positions.length;

  return (
    <Card className="grid grid-cols-2 divide-x divide-hairline p-0 sm:grid-cols-4">
      {(
        [
          ["Сумма закупки", work.total, ""],
          ["Себестоимость", work.cost, ""],
          [
            "Заработок",
            прибыль,
            прибыль !== null && прибыль <= 0 ? "text-critical" : "",
          ],
          [
            "Цена известна",
            null,
            "",
            `${work.priced} из ${work.positions.length}`,
          ],
        ] as const
      ).map(([label, value, tone, text]) => (
        <div key={label} className="px-5 py-3">
          <div className="text-xs text-ink-muted">{label}</div>
          <div className={cx("mt-0.5 font-medium tabular-nums text-ink", tone)}>
            {text ?? (value === null ? "—" : `${money(value)} ₸`)}
          </div>
          {label === "Цена известна" && неполно && (
            <div className="mt-0.5 text-xs text-warning">
              остальное ещё ищут
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}

/** Что отделы написали друг другу. Пустое не показывается. */
function Notes({ work }: { work: Work }) {
  const заметки = [
    ["Разбор просит", work.analysis_note],
    ["Снабжение отвечает", work.supply_note],
  ].filter(([, text]) => text) as [string, string][];

  if (!заметки.length) return null;
  return (
    <div className="space-y-2">
      {заметки.map(([label, text]) => (
        <Card key={label} className="px-5 py-3">
          <div className="text-xs font-medium text-ink-muted">{label}</div>
          <p className="mt-1 text-sm whitespace-pre-line text-ink">{text}</p>
        </Card>
      ))}
    </div>
  );
}

function PositionCard({
  work,
  position,
  number,
  analysis,
  editable,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  number: number;
  analysis: boolean;
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [asking, setAsking] = useState(false);

  return (
    <Card className="overflow-hidden p-0">
      <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-hairline bg-plane px-5 py-3">
        <div className="min-w-0">
          <div className="text-xs text-ink-muted tabular-nums">
            {number}. {position.code}
          </div>
          <h3 className="mt-0.5 text-sm font-medium break-words text-ink">
            {position.title}
          </h3>
        </div>
        <div className="text-xs text-ink-muted tabular-nums">
          {position.quantity !== null && (
            <>
              {money(position.quantity)} {position.unit || "шт"}
            </>
          )}
          {position.total !== null && ` · ${money(position.total)} ₸`}
        </div>
      </header>

      <Documents position={position} />

      <div className="px-5 py-3">
        <div className="mb-2 text-xs font-medium text-ink-muted">
          ГДЕ КУПИТЬ
        </div>
        {position.options.length === 0 ? (
          <p className="text-sm text-ink-muted">
            Вариантов пока нет.{" "}
            {analysis
              ? "Подтвердите поставщика или закажите поиск у снабжения."
              : "Разбор ничего не приложил — ищем сами."}
          </p>
        ) : (
          <ul className="space-y-2">
            {position.options.map((option) => (
              <OptionRow
                key={option.id}
                work={work}
                option={option}
                analysis={analysis}
                editable={editable}
                onDone={onDone}
              />
            ))}
          </ul>
        )}

        {editable && (
          <div className="mt-3 flex flex-wrap gap-2">
            {analysis ? (
              <Button variant="ghost" onClick={() => setAsking(true)}>
                + Заказать поиск у снабжения
              </Button>
            ) : (
              <Button variant="ghost" onClick={() => setAdding(true)}>
                + Добавить вариант
              </Button>
            )}
          </div>
        )}

        {asking && (
          <AskForm
            work={work}
            position={position}
            onDone={(next) => {
              setAsking(false);
              onDone(next);
            }}
            onCancel={() => setAsking(false)}
          />
        )}
        {adding && (
          <OptionForm
            title="Новый вариант"
            onSubmit={(fields) =>
              worksApi.addOption(work.id, position.id, fields)
            }
            onDone={(next) => {
              setAdding(false);
              onDone(next);
            }}
            onCancel={() => setAdding(false)}
          />
        )}
      </div>
    </Card>
  );
}

/** Техническое задание позиции — то, по чему снабжение и поймёт, что искать. */
function Documents({ position }: { position: WorkPosition }) {
  const [open, setOpen] = useState(false);
  if (!position.documents.length) return null;

  return (
    <div className="border-b border-hairline px-5 py-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-xs text-series-1 hover:underline"
      >
        {open ? "Скрыть" : "Показать"} документы позиции (
        {position.documents.length})
      </button>
      {open && (
        <ul className="mt-2 space-y-1">
          {position.documents.map((file, index) => (
            <li key={index} className="text-sm">
              <span className="mr-2 text-xs text-ink-muted">{file.label}</span>
              {file.link ? (
                <a
                  href={file.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-series-1 underline decoration-series-1/30 underline-offset-2"
                >
                  {file.text}
                </a>
              ) : (
                <span className="text-ink-muted">{file.text}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const SOURCES: Record<WorkOption["source"], { label: string; tone: string }> = {
  found: { label: "нашла модель", tone: "text-ink-muted" },
  asked: { label: "заявка разбора", tone: "text-warning" },
  supply: { label: "нашло снабжение", tone: "text-good" },
};

function OptionRow({
  work,
  option,
  analysis,
  editable,
  onDone,
}: {
  work: Work;
  option: WorkOption;
  analysis: boolean;
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [editing, setEditing] = useState(false);
  const choose = useMutation({
    mutationFn: () => worksApi.choose(work.id, option.id),
    onSuccess: onDone,
  });
  const drop = useMutation({
    mutationFn: () => worksApi.dropOption(work.id, option.id),
    onSuccess: onDone,
  });

  // Заявка разбора: заполнено одно название, остальное выясняет снабжение.
  const заявка = option.source === "asked" && option.price === null;

  if (editing)
    return (
      <li>
        <OptionForm
          title="Правка варианта"
          value={option}
          onSubmit={(fields) => worksApi.editOption(work.id, option.id, fields)}
          onDone={(next) => {
            setEditing(false);
            onDone(next);
          }}
          onCancel={() => setEditing(false)}
        />
      </li>
    );

  return (
    <li
      className={cx(
        "rounded-[8px] border px-3 py-2.5",
        option.chosen ? "border-good/40 bg-good/5" : "border-hairline",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium break-words text-ink">
              {option.supplier || option.name || "Без названия"}
            </span>
            <span className={cx("text-xs", SOURCES[option.source].tone)}>
              {SOURCES[option.source].label}
            </span>
            {option.chosen && (
              <span className="rounded-full bg-good/15 px-2 py-0.5 text-xs font-medium text-good">
                ✓ подтверждён
              </span>
            )}
          </div>

          {заявка ? (
            <p className="mt-1 text-sm text-ink-secondary">
              «{option.name}» — цену и поставщика выясняет снабжение
            </p>
          ) : (
            <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-xs">
              <Pair
                label="Цена"
                value={option.price === null ? "—" : `${money(option.price)} ₸`}
              />
              <Pair
                label="Срок"
                value={
                  option.delivery_days === null
                    ? "не указан"
                    : `${option.delivery_days} дн.`
                }
                warn={option.delivery_days === null}
              />
              {option.marketplace && (
                <Pair label="Площадка" value={option.marketplace} />
              )}
              {option.country && <Pair label="Страна" value={option.country} />}
              {option.url && (
                <a
                  href={option.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-series-1 underline decoration-series-1/30 underline-offset-2"
                >
                  Открыть ↗
                </a>
              )}
            </dl>
          )}
          {option.note && (
            <p className="mt-1 text-xs text-ink-muted">{option.note}</p>
          )}
        </div>

        {editable && (
          <div className="flex shrink-0 items-center gap-1">
            {analysis && !option.chosen && !заявка && (
              <Button
                variant="secondary"
                onClick={() => choose.mutate()}
                disabled={choose.isPending}
                title="Подтвердить поставщика: остальные найденные по этой позиции уйдут"
              >
                Подтвердить
              </Button>
            )}
            {!analysis && (
              <Button
                variant="ghost"
                onClick={() => setEditing(true)}
                title="Поправить цену, ссылку и срок поставки"
              >
                ✎ Править
              </Button>
            )}
            <button
              type="button"
              onClick={() => drop.mutate()}
              disabled={drop.isPending}
              aria-label="Убрать вариант"
              title="Убрать вариант"
              className="rounded-[6px] px-1.5 py-1 text-xs text-ink-muted transition hover:bg-critical/10 hover:text-critical"
            >
              ✕
            </button>
          </div>
        )}
      </div>
      {drop.isError && (
        <p className="mt-1.5 text-xs text-critical">
          {drop.error instanceof Error ? drop.error.message : "Не получилось"}
        </p>
      )}
      {choose.isError && (
        <p className="mt-1.5 text-xs text-critical">
          {choose.error instanceof Error
            ? choose.error.message
            : "Не получилось"}
        </p>
      )}
    </li>
  );
}

function Pair({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <span className="flex gap-1.5">
      <dt className="text-ink-muted">{label}</dt>
      <dd className={cx("tabular-nums", warn ? "text-warning" : "text-ink")}>
        {value}
      </dd>
    </span>
  );
}

/** «Найдите вот это»: заполняется одно название — остальное работа снабжения. */
function AskForm({
  work,
  position,
  onDone,
  onCancel,
}: {
  work: Work;
  position: WorkPosition;
  onDone: (work: Work) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(position.title);
  const ask = useMutation({
    mutationFn: () => worksApi.ask(work.id, position.id, name),
    onSuccess: onDone,
  });

  return (
    <div className="mt-3 rounded-[8px] border border-hairline bg-plane px-3 py-3">
      <label className="block text-xs font-medium text-ink-muted">
        Что искать снабжению
      </label>
      <p className="mt-1 mb-2 text-xs text-ink-muted">
        Найденное моделью по этой позиции уйдёт: заказ поиска и означает, что
        оно не подходит. Подтверждённый вами поставщик останется.
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Название товара, как его искать"
          className="min-w-0 flex-1 rounded-[8px] border border-baseline bg-surface px-3 py-1.5 text-sm text-ink focus:border-series-1 focus:outline-none"
        />
        <Button
          variant="primary"
          onClick={() => ask.mutate()}
          disabled={ask.isPending || !name.trim()}
        >
          Заказать
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Отмена
        </Button>
      </div>
      {ask.isError && (
        <p className="mt-1.5 text-xs text-critical">
          {ask.error instanceof Error ? ask.error.message : "Не получилось"}
        </p>
      )}
    </div>
  );
}

/** Передача другому отделу: комментарий и одна кнопка. */
function HandOver({
  work,
  analysis,
  onDone,
}: {
  work: Work;
  analysis: boolean;
  onDone: (work: Work) => void;
}) {
  const [note, setNote] = useState("");
  const send = useMutation({
    mutationFn: () => worksApi.handOver(work.id, note),
    onSuccess: (next) => {
      setNote("");
      onDone(next);
    },
  });

  const кому = analysis ? "снабжению" : "разбору";
  return (
    <Card className="px-5 py-4">
      <label className="block text-sm font-medium text-ink">
        Комментарий {кому}
      </label>
      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        rows={3}
        placeholder={
          analysis
            ? "Что важно знать: сроки, требования заказчика, на что смотреть"
            : "Что нашли, чего нет, на что обратить внимание"
        }
        className="mt-2 w-full rounded-[8px] border border-baseline bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-series-1 focus:outline-none"
      />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => send.mutate()}
          disabled={send.isPending}
        >
          {send.isPending ? "Отправляем…" : `Отправить ${кому}`}
        </Button>
        <span className="text-xs text-ink-muted">
          {analysis
            ? "После отправки лот перейдёт снабжению — править его будет уже оно"
            : "Лот вернётся разбору с подтверждёнными ценами"}
        </span>
      </div>
      {send.isError && (
        <p className="mt-2 text-sm text-critical">
          {send.error instanceof Error ? send.error.message : "Не отправилось"}
        </p>
      )}
    </Card>
  );
}
