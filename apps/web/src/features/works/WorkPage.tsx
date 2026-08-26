/**
 * Лот в работе: один экран на два отдела.
 *
 * Экран один, а показывает он разное — и это не ветвление ради экономии.
 * Отделы смотрят на один и тот же лот, и расхождение между «моей страницей» и
 * «его страницей» в двух файлах кончается тем, что позиция есть у одного и
 * нет у другого.
 *
 * Разбор видит деньги, подтверждает поставщиков и пишет задание. Снабжение
 * видит задание и «где купить»: ни сумм, ни исходных документов заказчика ему
 * не приходит — не скрыто вёрсткой, а отсутствует в ответе.
 *
 * Позиции — таблицей. В лоте их шесть, у каждой по три-четыре варианта, и
 * стопкой карточек это стена, в которой не найти ни количество, ни сумму.
 * Строка отвечает на «где я стою по этой позиции», раскрытие — на «что с ней
 * делать»: задание и варианты закупки.
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
import { formatDate } from "@/features/worklist/format";
import { Sourcing } from "./Sourcing";
import { Spec } from "./Spec";

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
        <Summary work={data} analysis={analysis} mine={мой} />
        <Notes work={data} />
        <Positions
          work={data}
          analysis={analysis}
          editable={мой}
          onDone={refresh}
        />
        {мой && <HandOver work={data} analysis={analysis} onDone={refresh} />}
      </div>
    </>
  );
}

/**
 * Шапка: где лот на пути и что с деньгами.
 *
 * Ход процесса — тремя шагами, а не одним словом состояния. Слово отвечает
 * «где сейчас», шаги — «где сейчас и что дальше»; человеку, который в этом
 * процессе третий день, второе и нужно.
 */
function Summary({
  work,
  analysis,
  mine,
}: {
  work: Work;
  analysis: boolean;
  mine: boolean;
}) {
  const прибыль =
    work.total !== null && work.cost !== null ? work.total - work.cost : null;
  const неполно = work.priced < work.positions.length;
  const сроки = withDates(work);

  return (
    <Card className="p-0">
      <Flow work={work} mine={mine} />
      <div className="grid grid-cols-2 gap-px bg-hairline md:grid-cols-4">
        <Cell label="Позиций" value={String(work.positions.length)} />
        {analysis ? (
          <>
            <Cell
              label="Сумма закупки"
              value={work.total === null ? "—" : money(work.total)}
              unit="₸"
            />
            <Cell
              label="Себестоимость"
              value={work.cost === null ? "—" : money(work.cost)}
              unit="₸"
              hint={
                неполно
                  ? `цена известна по ${work.priced} из ${work.positions.length}`
                  : undefined
              }
              tone={неполно ? "warning" : undefined}
            />
            <Cell
              label="Заработок"
              value={прибыль === null ? "—" : money(прибыль)}
              unit="₸"
              tone={прибыль !== null && прибыль > 0 ? "good" : "critical"}
              hint={неполно ? "по посчитанным позициям" : undefined}
            />
          </>
        ) : (
          <>
            <Cell
              label="Цена найдена"
              value={`${work.priced} из ${work.positions.length}`}
              tone={неполно ? "warning" : "good"}
            />
            <Cell
              label="Сроки проставлены"
              value={`${сроки} из ${work.positions.length}`}
              tone={сроки < work.positions.length ? "warning" : "good"}
            />
            <Cell
              label="Задание"
              value="от отдела разбора"
              hint="раскройте позицию, чтобы прочитать"
            />
          </>
        )}
      </div>
    </Card>
  );
}

/**
 * Путь лота тремя шагами.
 *
 * Кто нажимает кнопку — сотрудник, который в процессе третий день. «Стадия:
 * supply» ему не говорит ничего, а «сейчас у снабжения, дальше вернётся к вам»
 * говорит всё. Цвет здесь не единственный признак: шаг подписан словами.
 */
function Flow({ work, mine }: { work: Work; mine: boolean }) {
  const шаги: { key: Work["stage"]; title: string; hint: string }[] = [
    { key: "analysis", title: "Разбор выбирает", hint: "поставщики и задание" },
    { key: "supply", title: "Снабжение уточняет", hint: "цены и сроки" },
    { key: "returned", title: "Готово к КП", hint: "цены подтверждены" },
  ];
  const сейчас = шаги.findIndex((шаг) => шаг.key === work.stage);

  return (
    <div className="flex flex-wrap items-stretch gap-px border-b border-hairline bg-hairline">
      {шаги.map((шаг, index) => {
        const пройден = index < сейчас;
        const текущий = index === сейчас;
        return (
          <div
            key={шаг.key}
            className={cx(
              "flex min-w-52 flex-1 items-center gap-2.5 px-4 py-2.5",
              текущий ? "bg-series-1/10" : "bg-surface",
            )}
          >
            <span
              className={cx(
                "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                пройден && "bg-good text-white",
                текущий && "bg-series-1 text-white",
                !пройден && !текущий && "bg-plane text-ink-muted",
              )}
            >
              {пройден ? "✓" : index + 1}
            </span>
            <span className="min-w-0">
              <span
                className={cx(
                  "block truncate text-sm",
                  текущий ? "font-semibold text-ink" : "text-ink-secondary",
                )}
              >
                {шаг.title}
              </span>
              <span className="block truncate text-xs text-ink-muted">
                {текущий && mine ? "сейчас ваш ход" : шаг.hint}
              </span>
            </span>
            {текущий && work.sent_at && (
              <span className="ml-auto shrink-0 text-xs text-ink-muted">
                с {formatDate(work.sent_at)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Cell({
  label,
  value,
  unit,
  hint,
  tone,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: "good" | "warning" | "critical";
}) {
  const цвет =
    tone === "good"
      ? "text-good"
      : tone === "warning"
        ? "text-warning"
        : tone === "critical"
          ? "text-critical"
          : "text-ink";
  return (
    <div className="bg-surface px-5 py-3">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className={cx("text-lg font-semibold tabular-nums", цвет)}>
          {value}
        </span>
        {unit && <span className="text-xs text-ink-secondary">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 text-xs text-ink-muted">{hint}</div>}
    </div>
  );
}

/** По скольким позициям снабжение уже проставило срок поставки. */
function withDates(work: Work): number {
  return work.positions.filter((position) =>
    position.options.some((option) => option.delivery_days !== null),
  ).length;
}

/** Что просил разбор и что ответило снабжение. Пустые не показываются. */
function Notes({ work }: { work: Work }) {
  const записки = [
    work.analysis_note && {
      кто: "Отдел разбора просит",
      текст: work.analysis_note,
      тон: "border-l-series-1",
    },
    work.supply_note && {
      кто: "Снабжение отвечает",
      текст: work.supply_note,
      тон: "border-l-good",
    },
  ].filter(Boolean) as { кто: string; текст: string; тон: string }[];

  if (!записки.length) return null;

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {записки.map((записка) => (
        <Card
          key={записка.кто}
          className={cx("border-l-2 px-4 py-3", записка.тон)}
        >
          <div className="text-xs font-medium text-ink-muted">
            {записка.кто}
          </div>
          <p className="mt-1 text-sm whitespace-pre-wrap text-ink">
            {записка.текст}
          </p>
        </Card>
      ))}
    </div>
  );
}

/**
 * Состояние позиции: что с ней делать.
 *
 * Слова у отделов разные, потому что «готово» у них разное. Разбор готов, когда
 * выбран поставщик; снабжение — когда проставлены цена и срок. Одно слово на
 * двоих означало бы, что одному из них оно врёт.
 */
function stateOf(
  position: WorkPosition,
  analysis: boolean,
): { label: string; tone: string } {
  const выбран = position.options.some((option) => option.chosen);
  const заявка = position.options.some((option) => option.source === "asked");
  const есть_цена = position.options.some((option) => option.price !== null);

  if (!position.options.length)
    return { label: "Пусто", tone: "bg-critical/10 text-critical" };

  if (analysis) {
    if (выбран) return { label: "Подтверждён", tone: "bg-good/15 text-good" };
    if (заявка)
      return { label: "Заказан поиск", tone: "bg-warning/15 text-warning" };
    return { label: "Ждёт выбора", tone: "bg-series-1/10 text-series-1" };
  }

  if (!есть_цена)
    return { label: "Нужно найти", tone: "bg-warning/15 text-warning" };
  if (position.options.every((option) => option.delivery_days !== null))
    return { label: "Готово", tone: "bg-good/15 text-good" };
  return { label: "Нужен срок", tone: "bg-series-1/10 text-series-1" };
}

/** Вариант, по которому считается позиция: самый дешёвый из тех, где есть цена. */
function bestOf(position: WorkPosition): WorkOption | null {
  const с_ценой = position.options.filter((option) => option.price !== null);
  if (!с_ценой.length) return null;
  const выбран = с_ценой.find((option) => option.chosen);
  return (
    выбран ??
    с_ценой.reduce((left, right) =>
      (left.price ?? 0) <= (right.price ?? 0) ? left : right,
    )
  );
}

function Positions({
  work,
  analysis,
  editable,
  onDone,
}: {
  work: Work;
  analysis: boolean;
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(() => {
    // Одна позиция — раскрываем сразу: прятать единственное содержимое за
    // щелчком незачем.
    return new Set(work.positions.length === 1 ? [work.positions[0].id] : []);
  });

  const toggle = (id: string) =>
    setOpen((было) => {
      const стало = new Set(было);
      if (!стало.delete(id)) стало.add(id);
      return стало;
    });

  const все = open.size === work.positions.length;

  return (
    <Card className="p-0">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-5 py-2.5">
        <h3 className="text-sm font-semibold text-ink">
          Позиции лота
          <span className="ml-1.5 font-normal text-ink-muted">
            {work.positions.length}
          </span>
        </h3>
        <button
          type="button"
          onClick={() =>
            setOpen(
              все
                ? new Set()
                : new Set(work.positions.map((position) => position.id)),
            )
          }
          className="text-xs text-series-1 transition hover:underline"
        >
          {все ? "Свернуть все" : "Раскрыть все"}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-hairline bg-plane text-left text-xs text-ink-secondary">
              <th className="w-8 px-2 py-2.5" />
              <th className="w-10 px-2 py-2.5 text-right font-medium">№</th>
              <th className="w-24 px-2 py-2.5 font-medium">Код</th>
              <th className="px-2 py-2.5 font-medium">Наименование</th>
              <th className="w-24 px-2 py-2.5 text-right font-medium">
                Кол-во
              </th>
              {analysis ? (
                <>
                  <th className="w-36 px-2 py-2.5 text-right font-medium">
                    Сумма, ₸
                  </th>
                  <th className="w-36 px-2 py-2.5 text-right font-medium">
                    Закупка, ₸
                  </th>
                  <th className="w-36 px-2 py-2.5 text-right font-medium">
                    Заработок, ₸
                  </th>
                </>
              ) : (
                <>
                  <th className="w-44 px-2 py-2.5 font-medium">Поставщик</th>
                  <th className="w-32 px-2 py-2.5 text-right font-medium">
                    Цена, ₸
                  </th>
                </>
              )}
              <th className="w-24 px-2 py-2.5 text-right font-medium">Срок</th>
              <th className="w-32 px-2 py-2.5 font-medium">Состояние</th>
            </tr>
          </thead>
          <tbody>
            {work.positions.map((position, index) => (
              <PositionRows
                key={position.id}
                work={work}
                position={position}
                index={index + 1}
                analysis={analysis}
                editable={editable}
                open={open.has(position.id)}
                onToggle={() => toggle(position.id)}
                onDone={onDone}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function PositionRows({
  work,
  position,
  index,
  analysis,
  editable,
  open,
  onToggle,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  index: number;
  analysis: boolean;
  editable: boolean;
  open: boolean;
  onToggle: () => void;
  onDone: (work: Work) => void;
}) {
  const лучший = bestOf(position);
  const состояние = stateOf(position, analysis);
  const количество = position.quantity ?? 1;
  const закупка = лучший?.price != null ? лучший.price * количество : null;
  const заработок =
    закупка !== null && position.total !== null
      ? position.total - закупка
      : null;
  const колонок = analysis ? 10 : 9;

  return (
    <>
      <tr
        onClick={onToggle}
        className={cx(
          "cursor-pointer border-b border-hairline transition",
          open ? "bg-plane" : "hover:bg-plane/60",
        )}
      >
        <td className="px-2 py-2.5 align-top text-ink-muted">
          <span
            className={cx(
              "inline-block transition-transform",
              open && "rotate-90",
            )}
          >
            ▸
          </span>
        </td>
        <td className="px-2 py-2.5 text-right align-top tabular-nums text-ink-muted">
          {index}
        </td>
        <td className="px-2 py-2.5 align-top font-medium tabular-nums text-series-1">
          {position.code || "—"}
        </td>
        <td className="px-2 py-2.5 align-top">
          <div className="text-ink">{position.title}</div>
          {!position.spec.trim() && (
            <div className="mt-0.5 text-xs text-critical">
              нет технического задания
            </div>
          )}
        </td>
        <td className="px-2 py-2.5 text-right align-top tabular-nums text-ink">
          {position.quantity === null
            ? "—"
            : `${money(position.quantity)} ${position.unit}`.trim()}
        </td>

        {analysis ? (
          <>
            <td className="px-2 py-2.5 text-right align-top tabular-nums text-ink">
              {position.total === null ? "—" : money(position.total)}
            </td>
            <td className="px-2 py-2.5 text-right align-top tabular-nums text-ink">
              {закупка === null ? (
                <span className="text-ink-muted">не посчитана</span>
              ) : (
                money(закупка)
              )}
            </td>
            <td
              className={cx(
                "px-2 py-2.5 text-right align-top font-medium tabular-nums",
                заработок === null
                  ? "text-ink-muted"
                  : заработок > 0
                    ? "text-good"
                    : "text-critical",
              )}
            >
              {заработок === null
                ? "—"
                : `${заработок > 0 ? "+" : "−"}${money(Math.abs(заработок))}`}
            </td>
          </>
        ) : (
          <>
            <td className="px-2 py-2.5 align-top text-ink-secondary">
              {лучший?.supplier || (
                <span className="text-ink-muted">не выбран</span>
              )}
              {position.options.length > 1 && (
                <span className="ml-1 text-xs text-ink-muted">
                  +{position.options.length - 1}
                </span>
              )}
            </td>
            <td className="px-2 py-2.5 text-right align-top tabular-nums text-ink">
              {лучший?.price == null ? (
                <span className="text-warning">ищут</span>
              ) : (
                money(лучший.price)
              )}
            </td>
          </>
        )}

        <td
          className={cx(
            "px-2 py-2.5 text-right align-top tabular-nums",
            лучший?.delivery_days == null ? "text-warning" : "text-ink",
          )}
        >
          {лучший?.delivery_days == null
            ? "не указан"
            : `${лучший.delivery_days} дн.`}
        </td>
        <td className="px-2 py-2.5 align-top">
          <span
            className={cx(
              "inline-block rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
              состояние.tone,
            )}
          >
            {состояние.label}
          </span>
        </td>
      </tr>

      {open && (
        <tr className="border-b border-hairline bg-plane/40">
          <td colSpan={колонок} className="p-0">
            <div className="space-y-4 border-l-2 border-l-series-1 px-5 py-4">
              <Spec
                work={work}
                position={position}
                editable={editable && analysis}
                onDone={onDone}
              />
              <Sourcing
                work={work}
                position={position}
                analysis={analysis}
                editable={editable}
                onDone={onDone}
              />
              {analysis && <Documents position={position} />}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * Исходные бумаги позиции — только отделу разбора.
 *
 * Снабжению они не приходят вовсе: в ТЗ заказчика стоят цены ценового
 * заключения, реквизиты и печати. Вместо них — собранное задание.
 */
function Documents({ position }: { position: WorkPosition }) {
  if (!position.documents.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <span className="text-xs font-semibold tracking-wide text-ink-muted">
        ИСХОДНЫЕ ДОКУМЕНТЫ
      </span>
      {position.documents.map((file, index) => (
        <span key={index} className="text-sm">
          <span className="mr-1 text-xs text-ink-muted">{file.label}</span>
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
            <span className="text-ink-muted line-through">{file.text}</span>
          )}
        </span>
      ))}
      <span className="text-xs text-ink-muted">
        снабжение их не видит — ему уходит только задание
      </span>
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

  // Причины, по которым лот не уедет, — до нажатия, а не после. Человек и так
  // знает, что позиция пустая; узнавать это от красной надписи унизительно.
  const немые = analysis
    ? work.positions.filter(
        (position) => !position.options.length || !position.spec.trim(),
      )
    : [];

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
      {немые.length > 0 && (
        <p className="mt-2 rounded-[8px] bg-warning/10 px-3 py-2 text-sm text-ink">
          Не отправится, пока не закрыто:{" "}
          {немые
            .map(
              (position) =>
                `${position.code || position.title} — ${
                  !position.options.length ? "нет вариантов" : "нет задания"
                }`,
            )
            .join("; ")}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => send.mutate()}
          disabled={send.isPending || немые.length > 0}
        >
          {send.isPending ? "Отправляем…" : `Отправить ${кому}`}
        </Button>
        <span className="text-xs text-ink-muted">
          {analysis
            ? "Снабжение увидит задание и «где купить». Суммы и документы заказчика ему не уходят"
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
