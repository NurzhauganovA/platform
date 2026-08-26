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
 *
 * Позиции — таблицей, а не карточками. В лоте их шесть, у каждой по три-четыре
 * варианта, и стопкой карточек это стена, в которой не найти ни количество, ни
 * сумму. Таблица отвечает на «где я стою по каждой позиции» одним взглядом, а
 * варианты раскрываются по нажатию — тем же приёмом, которым работают со
 * списком закупок.
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
 * Строка итогов: где лот и что с деньгами.
 *
 * Первым — состояние: главный вопрос по лоту не «сколько», а «чьего хода
 * ждут». Деньги идут следом и только отделу разбора; снабжению вместо них
 * показывается его собственный итог — сколько цен найдено и сколько сроков
 * проставлено.
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
  const stage = STAGES[work.stage];
  const прибыль =
    work.total !== null && work.cost !== null ? work.total - work.cost : null;
  const неполно = work.priced < work.positions.length;
  const сроки = withDates(work);

  return (
    <Card className="p-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline px-5 py-3">
        <span
          className={cx(
            "rounded-full px-2.5 py-1 text-xs font-medium",
            stage.tone,
          )}
        >
          {stage.title}
        </span>
        <span className="text-sm text-ink-secondary">{stage.hint}</span>
        {!mine && (
          // Чужой ход — не «доступ запрещён», а «сейчас не ваша очередь».
          // Разница в том, ждать или звонить администратору.
          <span className="ml-auto text-xs text-ink-muted">
            Лот у другого отдела — можно смотреть, править нельзя
          </span>
        )}
      </div>

      <dl className="grid grid-cols-2 divide-x divide-hairline sm:grid-cols-4">
        <Cell label="Позиций" value={String(work.positions.length)} />
        {analysis ? (
          <>
            <Cell
              label="Сумма закупки"
              value={work.total === null ? "—" : `${money(work.total)} ₸`}
            />
            <Cell
              label="Себестоимость"
              value={work.cost === null ? "—" : `${money(work.cost)} ₸`}
              hint={
                неполно
                  ? `цена известна по ${work.priced} из ${work.positions.length}`
                  : undefined
              }
              warn={неполно}
            />
            <Cell
              label="Заработок"
              value={прибыль === null ? "—" : `${money(прибыль)} ₸`}
              tone={прибыль !== null && прибыль <= 0 ? "text-critical" : ""}
            />
          </>
        ) : (
          <>
            <Cell
              label="Цена найдена"
              value={`${work.priced} из ${work.positions.length}`}
              warn={неполно}
            />
            <Cell
              label="Сроки проставлены"
              value={`${сроки} из ${work.positions.length}`}
              warn={сроки < work.positions.length}
            />
            <Cell label="Заказчик" value={work.customer || "—"} />
          </>
        )}
      </dl>
    </Card>
  );
}

function Cell({
  label,
  value,
  hint,
  tone,
  warn,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
  warn?: boolean;
}) {
  return (
    <div className="px-5 py-3">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd
        className={cx(
          "mt-0.5 font-medium tabular-nums",
          tone || (warn ? "text-warning" : "text-ink"),
        )}
      >
        {value}
      </dd>
      {hint && <div className="mt-0.5 text-xs text-ink-muted">{hint}</div>}
    </div>
  );
}

/** По скольким позициям снабжение уже проставило срок. */
function withDates(work: Work): number {
  return work.positions.filter((position) =>
    position.options.some((option) => option.delivery_days !== null),
  ).length;
}

/** Что отделы написали друг другу. Пустое не показывается. */
function Notes({ work }: { work: Work }) {
  const заметки = (
    [
      ["Разбор просит", work.analysis_note],
      ["Снабжение отвечает", work.supply_note],
    ] as const
  ).filter(([, text]) => text);

  if (!заметки.length) return null;
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {заметки.map(([label, text]) => (
        <Card key={label} className="px-5 py-3">
          <div className="text-xs font-medium text-ink-muted">{label}</div>
          <p className="mt-1 text-sm whitespace-pre-line text-ink">{text}</p>
        </Card>
      ))}
    </div>
  );
}

/**
 * Что с позицией: готова, ждёт решения, ищут.
 *
 * Считается по вариантам, а не хранится отдельно: отдельное поле пришлось бы
 * обновлять из четырёх мест, и однажды одно из них забыли бы.
 *
 * Слова у отделов разные, потому что «готово» у них разное: у разбора это
 * «поставщик подтверждён», у снабжения — «цена и срок проставлены».
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

/** Лучший вариант позиции — тот, по которому и считается себестоимость. */
function bestOf(position: WorkPosition): WorkOption | null {
  const с_ценой = position.options.filter((option) => option.price !== null);
  if (!с_ценой.length) return null;
  return с_ценой.reduce((low, option) =>
    (option.price ?? 0) < (low.price ?? 0) ? option : low,
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
  // Раскрытые позиции. Свёрнуты по умолчанию: обзорная таблица отвечает на
  // большинство вопросов, а шесть раскрытых списков — это снова стена.
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) => {
    const next = new Set(open);
    if (!next.delete(id)) next.add(id);
    setOpen(next);
  };

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
        <h2 className="text-sm font-semibold text-ink">Позиции лота</h2>
        <button
          type="button"
          onClick={() =>
            setOpen(
              open.size
                ? new Set()
                : new Set(work.positions.map((position) => position.id)),
            )
          }
          className="text-xs text-series-1 hover:underline"
        >
          {open.size ? "Свернуть все" : "Раскрыть все"}
        </button>
      </div>

      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-hairline bg-plane text-left text-xs text-ink-secondary">
            <th className="w-12 px-3 py-2 font-medium" />
            <th className="w-24 px-3 py-2 font-medium">Код</th>
            <th className="px-3 py-2 font-medium">Наименование</th>
            <th className="w-28 px-3 py-2 text-right font-medium">Кол-во</th>
            {analysis && (
              <th className="w-32 px-3 py-2 text-right font-medium">
                Сумма, ₸
              </th>
            )}
            <th className="w-44 px-3 py-2 font-medium">Поставщик</th>
            <th className="w-28 px-3 py-2 text-right font-medium">Цена, ₸</th>
            <th className="w-20 px-3 py-2 text-right font-medium">Срок</th>
            <th className="w-32 px-3 py-2 font-medium">Состояние</th>
          </tr>
        </thead>
        <tbody>
          {work.positions.map((position, index) => (
            <PositionRows
              key={position.id}
              work={work}
              position={position}
              number={index + 1}
              analysis={analysis}
              editable={editable}
              open={open.has(position.id)}
              onToggle={() => toggle(position.id)}
              onDone={onDone}
            />
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function PositionRows({
  work,
  position,
  number,
  analysis,
  editable,
  open,
  onToggle,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  number: number;
  analysis: boolean;
  editable: boolean;
  open: boolean;
  onToggle: () => void;
  onDone: (work: Work) => void;
}) {
  const state = stateOf(position, analysis);
  const best = bestOf(position);
  const columns = analysis ? 9 : 8;

  return (
    <>
      <tr
        onClick={onToggle}
        className={cx(
          "cursor-pointer border-b border-hairline",
          open ? "bg-series-1/5" : "hover:bg-plane",
        )}
      >
        <td className="px-3 py-2.5 align-top tabular-nums text-ink-muted">
          <span className="mr-1 inline-block w-3">{open ? "▾" : "▸"}</span>
          {number}
        </td>
        <td className="px-3 py-2.5 align-top text-xs tabular-nums text-ink-muted">
          {position.code}
        </td>
        <td className="px-3 py-2.5 align-top break-words text-ink">
          {position.title}
        </td>
        <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
          {position.quantity === null
            ? "—"
            : `${money(position.quantity)} ${position.unit || "шт"}`}
        </td>
        {analysis && (
          <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
            {position.total === null ? "—" : money(position.total)}
          </td>
        )}
        <td className="px-3 py-2.5 align-top break-words text-ink-secondary">
          {best ? (
            best.supplier || best.name || "—"
          ) : (
            <span className="text-ink-muted">не выбран</span>
          )}
          {position.options.length > 1 && (
            <span className="ml-1.5 text-xs text-ink-muted">
              +{position.options.length - 1}
            </span>
          )}
        </td>
        <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
          {best?.price == null ? "—" : money(best.price)}
        </td>
        <td
          className={cx(
            "px-3 py-2.5 text-right align-top tabular-nums",
            best?.delivery_days == null ? "text-warning" : "text-ink",
          )}
        >
          {best?.delivery_days == null ? "—" : `${best.delivery_days} дн.`}
        </td>
        <td className="px-3 py-2.5 align-top">
          <span
            className={cx(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              state.tone,
            )}
          >
            {state.label}
          </span>
        </td>
      </tr>

      {open && (
        <tr className="border-b border-hairline bg-plane/60">
          <td colSpan={columns} className="p-0">
            <Details
              work={work}
              position={position}
              analysis={analysis}
              editable={editable}
              onDone={onDone}
            />
          </td>
        </tr>
      )}
    </>
  );
}

/** Раскрытая позиция: варианты закупки и её документы. */
function Details({
  work,
  position,
  analysis,
  editable,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  analysis: boolean;
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [asking, setAsking] = useState(false);
  const [editingId, setEditingId] = useState("");

  const editing = position.options.find((option) => option.id === editingId);

  return (
    <div className="border-l-2 border-l-series-1 px-5 py-4">
      <Documents position={position} />

      <div className="mt-3 mb-2 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-ink-muted">ГДЕ КУПИТЬ</h4>
        {editable && (
          <Button
            variant="ghost"
            onClick={() => (analysis ? setAsking(true) : setAdding(true))}
          >
            {analysis ? "+ Заказать поиск" : "+ Добавить вариант"}
          </Button>
        )}
      </div>

      {position.options.length === 0 ? (
        <p className="rounded-[8px] border border-dashed border-hairline px-4 py-3 text-sm text-ink-muted">
          {analysis
            ? "Вариантов нет. Подтвердите поставщика или закажите поиск у снабжения — иначе лот не отправить."
            : "Разбор ничего не приложил — ищем сами."}
        </p>
      ) : (
        <OptionsTable
          work={work}
          position={position}
          analysis={analysis}
          editable={editable}
          onEdit={setEditingId}
          onDone={onDone}
        />
      )}

      {editing && (
        <OptionForm
          title="Правка варианта"
          value={editing}
          onSubmit={(fields) =>
            worksApi.editOption(work.id, editing.id, fields)
          }
          onDone={(next) => {
            setEditingId("");
            onDone(next);
          }}
          onCancel={() => setEditingId("")}
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
    </div>
  );
}

const SOURCES: Record<WorkOption["source"], { label: string; tone: string }> = {
  found: { label: "модель", tone: "text-ink-muted" },
  asked: { label: "заявка разбора", tone: "text-warning" },
  supply: { label: "снабжение", tone: "text-good" },
};

/**
 * Варианты — таблицей, а не карточками.
 *
 * Их сравнивают по цене и сроку, то есть читают колонкой сверху вниз. В
 * карточках цена каждый раз в новом месте, и сравнить четыре варианта можно
 * только выписав их на бумажку.
 */
function OptionsTable({
  work,
  position,
  analysis,
  editable,
  onEdit,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  analysis: boolean;
  editable: boolean;
  onEdit: (id: string) => void;
  onDone: (work: Work) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-[8px] border border-hairline bg-surface">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-hairline text-left text-xs text-ink-muted">
            <th className="px-3 py-2 font-medium">Поставщик</th>
            <th className="px-3 py-2 font-medium">Что покупаем</th>
            <th className="w-28 px-3 py-2 text-right font-medium">Цена, ₸</th>
            <th className="w-24 px-3 py-2 text-right font-medium">Срок</th>
            <th className="w-40 px-3 py-2 font-medium">Площадка</th>
            <th className="w-28 px-3 py-2 font-medium">Откуда</th>
            <th className="w-40 px-3 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {position.options.map((option) => (
            <OptionRow
              key={option.id}
              work={work}
              option={option}
              analysis={analysis}
              editable={editable}
              onEdit={() => onEdit(option.id)}
              onDone={onDone}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OptionRow({
  work,
  option,
  analysis,
  editable,
  onEdit,
  onDone,
}: {
  work: Work;
  option: WorkOption;
  analysis: boolean;
  editable: boolean;
  onEdit: () => void;
  onDone: (work: Work) => void;
}) {
  const choose = useMutation({
    mutationFn: () => worksApi.choose(work.id, option.id),
    onSuccess: onDone,
  });
  const drop = useMutation({
    mutationFn: () => worksApi.dropOption(work.id, option.id),
    onSuccess: onDone,
  });
  const беда = choose.error ?? drop.error;

  // Заявка разбора: заполнено одно название, остальное выясняет снабжение.
  const заявка = option.source === "asked" && option.price === null;

  return (
    <>
      <tr
        className={cx(
          "border-b border-hairline last:border-0",
          option.chosen && "bg-good/5",
        )}
      >
        <td className="px-3 py-2 align-top">
          <div className="flex items-start gap-1.5">
            {option.chosen && (
              <span className="text-good" title="Подтверждён разбором">
                ✓
              </span>
            )}
            <span className="break-words text-ink">
              {option.supplier || (заявка ? "—" : "без названия")}
            </span>
          </div>
        </td>
        <td className="px-3 py-2 align-top break-words text-ink-secondary">
          {option.name || "—"}
          {option.note && (
            <div className="mt-0.5 text-xs text-ink-muted">{option.note}</div>
          )}
        </td>
        <td className="px-3 py-2 text-right align-top tabular-nums text-ink">
          {option.price === null ? (
            <span className="text-warning">ищут</span>
          ) : (
            money(option.price)
          )}
        </td>
        <td
          className={cx(
            "px-3 py-2 text-right align-top tabular-nums",
            option.delivery_days === null ? "text-warning" : "text-ink",
          )}
        >
          {option.delivery_days === null ? "—" : `${option.delivery_days} дн.`}
        </td>
        <td className="px-3 py-2 align-top text-ink-secondary">
          {option.url ? (
            <a
              href={option.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-series-1 underline decoration-series-1/30 underline-offset-2"
            >
              {option.marketplace || "открыть"} ↗
            </a>
          ) : (
            option.marketplace || "—"
          )}
          {option.country && (
            <div className="text-xs text-ink-muted">{option.country}</div>
          )}
        </td>
        <td
          className={cx(
            "px-3 py-2 align-top text-xs",
            SOURCES[option.source].tone,
          )}
        >
          {SOURCES[option.source].label}
        </td>
        <td className="px-3 py-2 align-top">
          {editable && (
            <div className="flex items-center justify-end gap-1">
              {analysis && !option.chosen && !заявка && (
                <Button
                  variant="secondary"
                  onClick={() => choose.mutate()}
                  disabled={choose.isPending}
                  title="Остальные найденные по этой позиции уйдут"
                >
                  Подтвердить
                </Button>
              )}
              {!analysis && (
                <Button
                  variant="ghost"
                  onClick={onEdit}
                  title="Цена, ссылка, срок поставки"
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
        </td>
      </tr>
      {беда && (
        <tr>
          <td colSpan={7} className="px-3 pb-2 text-xs text-critical">
            {беда instanceof Error ? беда.message : "Не получилось"}
          </td>
        </tr>
      )}
    </>
  );
}

/** Техническое задание позиции — то, по чему снабжение и поймёт, что искать. */
function Documents({ position }: { position: WorkPosition }) {
  if (!position.documents.length)
    return (
      <p className="text-xs text-ink-muted">
        Документов по этой позиции в архиве нет.
      </p>
    );

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <span className="text-xs font-semibold text-ink-muted">ДОКУМЕНТЫ</span>
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
    </div>
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
    <div className="mt-3 rounded-[8px] border border-warning/40 bg-warning/5 px-4 py-3">
      <div className="text-xs font-semibold text-ink-muted">
        ЗАКАЗ ПОИСКА У СНАБЖЕНИЯ
      </div>
      <p className="mt-1 mb-2 text-xs text-ink-secondary">
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
