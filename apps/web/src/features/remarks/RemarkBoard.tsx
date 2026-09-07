/**
 * Доска обсуждений: колонка — этап, перетаскивание — перевод.
 *
 * Этапов пять, и они умещаются на экран без прокрутки. Последняя колонка —
 * «Не требуется»: замечание, которое решили не писать, это тоже решение, и
 * оно должно быть видно, а не исчезать из списка.
 *
 * **Отправка необратима.** Из «Отправлены» перетащить нельзя — сервер такого
 * перехода не даёт, и доска это просто отражает: карточка не берётся.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { remarks as api, type Remark, type Stage } from "@/api/remarks";
import { ApiError } from "@/api/client";
import { Badge, Button, Card as Panel, Pair, cx, money } from "@/ui";
import { Board, Peek, type BoardColumn } from "@/ui/board";
import { OutcomeWord, STAGE_RULE, WritingNote } from "./marks";

const COLUMNS: BoardColumn<Stage>[] = [
  { key: "drafting", title: "Пишутся", rule: STAGE_RULE.drafting },
  { key: "moderation", title: "На проверке", rule: STAGE_RULE.moderation },
  { key: "lawyers", title: "У юристов", rule: STAGE_RULE.lawyers },
  { key: "sent", title: "Отправлены", rule: STAGE_RULE.sent },
  {
    key: "not_needed",
    title: "Не требуется",
    rule: STAGE_RULE.not_needed,
    apart: true,
  },
];

export function RemarkBoard({ items }: { items: Remark[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [trouble, setTrouble] = useState("");
  const client = useQueryClient();

  const open = items.find((item) => item.id === openId) ?? null;

  const move = useMutation({
    mutationFn: ({ item, to }: { item: Remark; to: Stage }) =>
      api.move(item.id, to),
    onMutate: async ({ item, to }) => {
      setTrouble("");
      await client.cancelQueries({ queryKey: ["remarks"] });
      const before = client.getQueriesData<Remark[]>({ queryKey: ["remarks"] });
      client.setQueriesData<Remark[]>({ queryKey: ["remarks"] }, (now) =>
        (now ?? []).map((row) =>
          row.id === item.id ? { ...row, stage: to } : row,
        ),
      );
      return { before };
    },
    onError: (error, _sent, context) => {
      for (const [key, value] of context?.before ?? []) {
        client.setQueryData(key, value);
      }
      setTrouble(
        error instanceof ApiError ? error.message : "Перевод не прошёл",
      );
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["remarks"] });
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
            items={items}
            columnOf={(item) => item.stage}
            idOf={(item) => item.id}
            targets={(item) => item.can}
            onMove={(item, to) => move.mutate({ item, to })}
            onOpen={(item) => setOpenId(item.id)}
            openId={openId ?? undefined}
            empty="Здесь пока пусто"
            card={(item) => <Face remark={item} />}
          />
        </div>

        {open && <RemarkPeek remark={open} onClose={() => setOpenId(null)} />}
      </div>
    </div>
  );
}

/** Карточка: узнать замечание и понять, успеваем ли. */
function Face({ remark }: { remark: Remark }) {
  return (
    <>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[11px] text-ink-muted">
          {remark.code}
        </span>
        <span className="ml-auto">
          <WritingNote remark={remark} />
        </span>
      </div>

      <p className="mt-1 line-clamp-2 text-sm leading-snug text-ink">
        {remark.title}
      </p>

      <div className="mt-2 flex items-center gap-2">
        {remark.stage === "sent" ? (
          <OutcomeWord remark={remark} />
        ) : (
          <Left remark={remark} />
        )}
        <span
          className="ml-auto truncate text-[11px] text-ink-muted"
          title={remark.assignee ? `Ведёт ${remark.assignee}` : "Ничьё"}
        >
          {remark.assignee || "ничьё"}
        </span>
      </div>
    </>
  );
}

/** Срок — самое заметное: замечание пишется под окончание приёма заявок. */
function Left({ remark }: { remark: Remark }) {
  if (!remark.left) {
    return <span className="text-[11px] text-ink-muted">—</span>;
  }
  if (remark.overdue) {
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
        remark.burning
          ? "rounded-[4px] bg-critical/10 px-1.5 py-0.5 font-semibold text-critical"
          : "text-ink-secondary",
      )}
    >
      {remark.burning && <span aria-hidden>● </span>}
      {remark.left}
    </span>
  );
}

function RemarkPeek({
  remark,
  onClose,
}: {
  remark: Remark;
  onClose: () => void;
}) {
  return (
    <Peek
      title={remark.title}
      subtitle={`${remark.code} · ${remark.stage_name}`}
      onClose={onClose}
      footer={
        <Link to={`/goszakup/remarks/${remark.id}`}>
          <Button variant="primary" className="w-full">
            Открыть обсуждение
          </Button>
        </Link>
      }
    >
      <Row name="Заказчик" value={remark.customer || "—"} />
      <Row
        name="Сумма"
        value={remark.amount === null ? "—" : `${money(remark.amount)} ₸`}
      />
      <Row name="Осталось" value={remark.left || "—"} tone={remark.burning} />
      <Row name="Ведёт" value={remark.assignee || "ничьё"} />
      <Row name="Категория" value={remark.category || "—"} />
      <Row name="Код ЕНС ТРУ" value={remark.enstru_code || "—"} />

      {remark.stage === "sent" && (
        <div className="border-t border-hairline pt-3">
          <Pair
            top={
              <span className="flex items-center gap-2">
                Ответ заказчика
                <Badge
                  tone={
                    remark.outcome === "accepted"
                      ? "good"
                      : remark.outcome === "rejected"
                        ? "serious"
                        : "neutral"
                  }
                >
                  {remark.outcome_name}
                </Badge>
              </span>
            }
            bottom={remark.answer || "Ответа пока нет"}
          />
        </div>
      )}

      {remark.text && (
        <div className="border-t border-hairline pt-3">
          <Pair top="Текст" />
          <p className="mt-1 line-clamp-[12] text-xs leading-relaxed text-ink-secondary">
            {remark.text}
          </p>
        </div>
      )}

      {remark.trouble && (
        <p className="rounded-[6px] bg-warning/10 px-2.5 py-2 text-xs text-ink">
          {remark.trouble}
        </p>
      )}
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
