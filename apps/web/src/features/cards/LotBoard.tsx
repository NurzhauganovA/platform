/**
 * Доска лотов: колонка — состояние, перетаскивание — переход.
 *
 * Колонок одиннадцать по основному пути плюс три для сошедших с дистанции.
 * Все сразу, с прокруткой вбок: путь длинный и ветвится, а свёрнутый в пять
 * широких колонок он прячет точный статус внутрь карточки — и на планёрке
 * вопрос «что сейчас с этой закупкой» снова требует открыть каждую.
 *
 * На карточке — только то, по чему лот узнают и по чему решают, к нему ли
 * сейчас подходить: код, название, срок и кто ведёт. Остальное в панели сбоку.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  cardsApi,
  FLOW,
  OFF_TRACK,
  type Card as Lot,
  type LotStatus,
} from "@/api/cards";
import { ApiError } from "@/api/client";
import { Badge, Button, Card as Panel, Pair, cx, money } from "@/ui";
import { Board, Peek, type BoardColumn } from "@/ui/board";

/** Цвет точки у заголовка колонки. Место в процессе, а не важность. */
const RULE: Record<LotStatus, string> = {
  new: "bg-baseline",
  discussion: "bg-series-5",
  analysis: "bg-series-1",
  approval: "bg-series-4",
  ready: "bg-series-3",
  awaiting: "bg-series-2",
  won: "bg-good",
  lost: "bg-hairline",
  contract: "bg-series-3",
  fulfilling: "bg-series-3",
  awaiting_payment: "bg-series-4",
  done: "bg-hairline",
  skipped: "bg-hairline",
  cancelled: "bg-hairline",
};

const OFF_NAMES: Record<string, string> = {
  skipped: "Пропускаем",
  lost: "Проиграли",
  cancelled: "Отменён",
};

const COLUMNS: BoardColumn<LotStatus>[] = [
  ...FLOW.map((step) => ({
    key: step.key,
    title: step.title,
    rule: RULE[step.key],
  })),
  ...OFF_TRACK.map((status, index) => ({
    key: status,
    title: OFF_NAMES[status] ?? status,
    rule: RULE[status],
    // Пунктиром и с отступом от основного пути: это не следующий шаг, а
    // выход из него.
    apart: index === 0,
  })),
];

export function LotBoard({ lots }: { lots: Lot[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [trouble, setTrouble] = useState("");
  const client = useQueryClient();

  const open = lots.find((item) => item.id === openId) ?? null;

  const move = useMutation({
    mutationFn: ({ lot, to }: { lot: Lot; to: LotStatus }) =>
      cardsApi.move(lot.id, to),
    // Карточка переезжает сразу, не дожидаясь ответа: перетаскивание, после
    // которого лот на полсекунды прыгает обратно, читается как сбой.
    onMutate: async ({ lot, to }) => {
      setTrouble("");
      await client.cancelQueries({ queryKey: ["cards"] });
      const before = client.getQueryData<Lot[]>(["cards"]);
      client.setQueryData<Lot[]>(["cards"], (now) =>
        (now ?? []).map((item) =>
          item.id === lot.id ? { ...item, status: to } : item,
        ),
      );
      return { before };
    },
    onError: (error, _sent, context) => {
      // Сервер отказал — возвращаем на место и говорим его словами. Молча
      // оставить карточку в новой колонке нельзя: человек уйдёт уверенным,
      // что перевёл.
      if (context?.before) client.setQueryData(["cards"], context.before);
      setTrouble(
        error instanceof ApiError ? error.message : "Перевод не прошёл",
      );
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["cards"] });
    },
  });

  return (
    <div className="space-y-3">
      {trouble && (
        <Panel className="border-critical/40 bg-critical/5 px-4 py-2.5">
          <p className="text-sm text-critical">{trouble}</p>
        </Panel>
      )}

      <div className="flex min-h-0 gap-3">
        <div className="min-w-0 flex-1">
          <Board
            columns={COLUMNS}
            items={lots}
            columnOf={(lot) => lot.status}
            idOf={(lot) => lot.id}
            // Куда можно — решает сервер: список приходит в `can` вместе с
            // лотом. Своя таблица переходов здесь разъехалась бы с той,
            // по которой сервер отвечает.
            targets={(lot) => lot.can}
            onMove={(lot, to) => move.mutate({ lot, to })}
            onOpen={(lot) => setOpenId(lot.id)}
            openId={openId ?? undefined}
            empty="Сюда пока никто не дошёл"
            card={(lot) => <Face lot={lot} />}
          />
        </div>

        {open && <LotPeek lot={open} onClose={() => setOpenId(null)} />}
      </div>
    </div>
  );
}

/** Карточка на доске. Минимум: узнать лот и понять, горит ли он. */
function Face({ lot }: { lot: Lot }) {
  const off = OFF_TRACK.includes(lot.status);
  return (
    <>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[11px] text-ink-muted">{lot.code}</span>
        {lot.open_tasks > 0 && (
          <span
            className="ml-auto text-[11px] tabular-nums text-ink-muted"
            title={`Открытых задач: ${lot.open_tasks}`}
          >
            {lot.open_tasks} зад.
          </span>
        )}
      </div>

      <p
        className={cx(
          "mt-1 line-clamp-2 text-sm leading-snug",
          off ? "text-ink-muted" : "text-ink",
        )}
      >
        {lot.title}
      </p>

      <div className="mt-2 flex items-center gap-2">
        <Left lot={lot} />
        <span
          className="ml-auto truncate text-[11px] text-ink-muted"
          title={lot.owner ? `Ведёт ${lot.owner}` : "Ответственного нет"}
        >
          {lot.owner || "ничьё"}
        </span>
      </div>
    </>
  );
}

/**
 * Срок — самое заметное на карточке.
 *
 * Доску заводили вместо таблицы, а в таблице по колонке сроков пробегали
 * глазами. На карточках такой колонки нет, и если срок набрать тем же серым,
 * что и остальное, горящий лот перестанет отличаться от спокойного.
 */
function Left({ lot }: { lot: Lot }) {
  if (!lot.left) return <span className="text-[11px] text-ink-muted">—</span>;
  if (lot.overdue) {
    return (
      <span className="text-[11px] text-ink-muted line-through">
        срок прошёл
      </span>
    );
  }
  return (
    <span
      className={cx(
        "text-[11px] tabular-nums whitespace-nowrap",
        lot.burning
          ? "rounded-[4px] bg-critical/10 px-1.5 py-0.5 font-semibold text-critical"
          : "text-ink-secondary",
      )}
    >
      {lot.burning && <span aria-hidden>● </span>}
      {lot.left}
    </span>
  );
}

/** Панель подробностей: то, чего нет на карточке, но что спрашивают первым. */
function LotPeek({ lot, onClose }: { lot: Lot; onClose: () => void }) {
  const signed = lot.approvals.filter(
    (sign) => sign.state === "approved",
  ).length;

  return (
    <Peek
      title={lot.title}
      subtitle={`${lot.code} · ${lot.status_name}`}
      onClose={onClose}
      footer={
        <Link to={`/work/lots/${lot.id}`}>
          <Button variant="primary" className="w-full">
            Открыть карточку
          </Button>
        </Link>
      }
    >
      <Row name="Заказчик" value={lot.customer || "—"} />
      <Row
        name="Сумма"
        value={lot.amount === null ? "—" : `${money(lot.amount)} ₸`}
      />
      <Row name="Приём до" value={lot.left || "—"} tone={lot.burning} />
      <Row name="Ведёт" value={lot.owner || "ничьё"} />
      <Row name="Менеджер" value={lot.manager || "—"} />
      <Row name="Категория" value={lot.category || "—"} />
      <Row name="Код ЕНС ТРУ" value={lot.enstru_code || "—"} />
      <Row name="Номер закупки" value={lot.source_number || lot.row_id} />

      <div className="border-t border-hairline pt-3">
        <Pair
          top={
            <span className="flex items-center gap-2">
              Подписи
              {lot.approved ? (
                <Badge tone="good">все собраны</Badge>
              ) : (
                <Badge tone="neutral">
                  {signed} из {lot.approvals.length}
                </Badge>
              )}
            </span>
          }
          bottom={
            lot.approved
              ? "Лот готов к участию"
              : "Готовым к участию лот не станет, пока не собраны все пять"
          }
        />
      </div>

      {lot.open_tasks > 0 && (
        <Row name="Открытых задач" value={String(lot.open_tasks)} />
      )}
      {lot.note && (
        <div className="border-t border-hairline pt-3">
          <Pair top="Заметка" bottom={lot.note} />
        </div>
      )}

      {/* Полное название — внизу и с прокруткой. У лотов портала в нём лежит
          техническая спецификация целиком: заголовком она занимает панель, а
          читают её всё-таки не первой. */}
      <div className="border-t border-hairline pt-3">
        <Pair top="Предмет закупки" />
        <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
          {lot.title}
        </p>
      </div>
    </Peek>
  );
}

function Row({
  name,
  value,
  tone,
}: {
  name: string;
  value: string;
  tone?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-xs text-ink-muted">{name}</span>
      <span
        className={cx(
          "min-w-0 truncate text-right text-sm",
          tone ? "font-semibold text-critical" : "text-ink",
        )}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}
