/**
 * Что нужно заказчику.
 *
 * Показывается, когда предложений конкурентов ещё нет. Это не заглушка вместо
 * сравнения, а рабочий экран: закупка без КП — обычное дело, и участвовать в
 * ней выгоднее всего, потому что конкурентов не видно. Заказчик в заключении
 * обычно ставит свой ориентир цены — выше него предлагать бессмысленно, и это
 * ровно та величина, от которой считается наша.
 */

import type { CaseComparison } from "@/api/tender";
import { Badge, Card, StatTile, money } from "@/ui";

export function Requested({ data }: { data: CaseComparison }) {
  const positions = data.requested;
  const withPrice = positions.filter((item) => item.customer_price != null);
  const ceiling = withPrice.reduce(
    (sum, item) => sum + (item.customer_price ?? 0) * (item.quantity ?? 1),
    0,
  );

  return (
    <div className="space-y-4">
      <Card className="border-series-1/40 bg-series-1/5 px-5 py-3.5">
        <p className="text-sm text-ink">
          <strong className="font-semibold">
            Предложений конкурентов пока нет.
          </strong>{" "}
          Это не повод пропускать закупку — наоборот: соперников не видно, и
          цену можно ставить от рынка. Запустите поиск на рынках, чтобы узнать
          себестоимость.
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile label="Позиций требуется" value={positions.length} />
        <StatTile
          label="Ориентир заказчика"
          value={ceiling ? money(ceiling) : "не указан"}
          unit={ceiling ? "₸" : undefined}
          hint={ceiling ? "выше этого предлагать бессмысленно" : undefined}
          tone="series-1"
        />
        <StatTile
          label="Документов заказчика"
          value={new Set(positions.map((item) => item.source_document)).size}
          hint="ТЗ и заключения"
        />
      </div>

      <Card title={`Что требуется (${positions.length})`}>
        <table className="w-full table-fixed text-sm">
          <colgroup>
            <col className="w-[36%]" />
            <col className="w-[34%]" />
            <col className="w-[13%]" />
            <col className="w-[17%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-hairline text-left text-xs text-ink-muted">
              <th className="w-12 px-3 py-2 text-right font-medium">№</th>
              <th className="px-5 py-2 font-medium">Позиция</th>
              <th className="py-2 font-medium">Характеристики</th>
              <th className="py-2 text-right font-medium">Кол-во</th>
              <th className="px-5 py-2 text-right font-medium">Ориентир, ₸</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((item, index) => (
              <tr
                key={item.name + index}
                className="border-b border-hairline last:border-0"
              >
                <td className="px-3 py-2 text-right align-top tabular-nums text-ink-muted">
                  {index + 1}
                </td>
                <td className="truncate px-5 py-2 text-ink" title={item.name}>
                  {item.name}
                </td>
                <td
                  className="truncate py-2 text-ink-muted"
                  title={item.specification ?? ""}
                >
                  {item.specification ?? "—"}
                </td>
                <td className="py-2 text-right text-ink-secondary">
                  {item.quantity ?? "—"} {item.unit ?? ""}
                </td>
                <td className="px-5 py-2 text-right text-ink">
                  {item.customer_price != null
                    ? money(item.customer_price)
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {data.risks.length > 0 && (
        <Card title="На что обратить внимание">
          <ul className="divide-y divide-hairline">
            {data.risks.map((risk) => (
              <li key={risk} className="flex gap-2.5 px-5 py-2.5">
                <span aria-hidden className="mt-0.5 shrink-0 text-warning">
                  ▲
                </span>
                <span className="text-sm text-ink">{risk}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.decision?.recommendation && (
        <Card title="Решение">
          <div className="space-y-2 px-5 py-4">
            <Badge tone="info">{data.decision.recommendation}</Badge>
            {data.decision.summary && (
              <p className="text-sm text-ink-secondary">
                {data.decision.summary}
              </p>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
