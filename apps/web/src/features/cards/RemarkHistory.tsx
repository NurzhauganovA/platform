/**
 * Хронология обсуждения: что делали с замечанием и кто.
 *
 * Собрать это из самого замечания нельзя — там хранятся только последние
 * значения: кем отправлено не хранится вовсе, текст модели затирается при
 * каждом перезапуске прогона, а правивший помнится один, последний. Поэтому
 * события записываются отдельно, а здесь только показываются.
 *
 * Открывают ленту в одном случае: пришёл отказ, и надо понять, что именно
 * ушло заказчику и чем оно отличалось от написанного моделью. Поэтому свёрнута
 * по умолчанию — в обычный день она не нужна, а места занимает экран.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { remarks, type Step } from "@/api/remarks";
import { Card as Panel, Spinner, cx } from "@/ui";
import { Chevron, stamp } from "./kit";

export function RemarkHistory({ remarkId }: { remarkId: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["remark-history", remarkId],
    queryFn: () => remarks.history(remarkId),
    // Читается по раскрытию, а не вместе со страницей: лента нужна изредка, а
    // запрос на каждое открытие обсуждения — это лишний круг до сервера там,
    // где смотрят на текст.
    enabled: open,
  });

  return (
    <Panel className="overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={cx(
          "flex w-full items-center gap-2 px-4 py-2.5 text-left transition",
          "hover:bg-plane/60",
        )}
      >
        <Chevron open={open} />
        <span className="text-[13px] font-medium text-ink">
          Хронология обсуждения
        </span>
        <span className="text-[11.5px] text-ink-muted">
          кто и что делал с замечанием
        </span>
      </button>

      {open && (
        <div className="border-t border-hairline px-4 py-3">
          {isLoading ? (
            <Spinner label="Читаем хронологию…" />
          ) : !data?.length ? (
            <p className="text-[12.5px] text-ink-muted">
              Пока ничего не записано. Хронология ведётся с того дня, как её
              завели: у давних обсуждений в ней только то, что удалось
              восстановить, — когда написала модель и когда отправили.
            </p>
          ) : (
            <ol className="flex flex-col gap-2.5">
              {data.map((step) => (
                <Line key={step.id} step={step} />
              ))}
            </ol>
          )}
        </div>
      )}
    </Panel>
  );
}

function Line({ step }: { step: Step }) {
  return (
    <li className="flex gap-2.5">
      {/* Точка и линия слева — как в ленте лота: глаз читает столбец сверху
          вниз, и без неё строки рассыпаются на отдельные абзацы. */}
      <span
        aria-hidden
        className={cx(
          "mt-[5px] h-2 w-2 shrink-0 rounded-full",
          step.by_machine ? "bg-series-2" : "bg-series-1",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-[12.5px] font-medium text-ink">
            {step.actor}
          </span>
          {/* Роль на момент действия: «Сулеймен (Обсуждение)». Сегодняшняя
              роль ответила бы неверно — человека переводят между отделами. */}
          {step.role && (
            <span className="text-[11.5px] text-ink-muted">({step.role})</span>
          )}
          <span className="text-[11.5px] whitespace-nowrap text-ink-muted tabular-nums">
            {stamp(step.at)}
          </span>
        </div>
        <p className="text-[12.5px] text-ink-secondary">{step.title}</p>
        {/* Текст обрезан сервером: лента читается целиком, и замечание на три
            тысячи знаков в ней — это второй экземпляр того, что лежит выше. */}
        {step.detail && (
          <p className="mt-0.5 line-clamp-3 text-[12px] leading-relaxed whitespace-pre-wrap text-ink-muted">
            {step.detail}
          </p>
        )}
      </div>
    </li>
  );
}
