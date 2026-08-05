/**
 * Сравнение предложений по позициям.
 *
 * Ради этого экрана разбор и делается. Пока цены разных КП не сведены по
 * позициям, сравнивать можно только итоговые суммы — а они складываются из
 * разного состава и потому мало о чём говорят.
 *
 * Таблица, а не диаграмма: значения надо читать точно и сравнивать построчно,
 * а не оценивать на глаз. Лучшая цена помечена и цветом, и значком — цвет сам
 * по себе неразличим, и полагаться на него нельзя.
 */

import { useQuery } from "@tanstack/react-query";
import { tender } from "@/api/tender";
import { Badge, Card, Collapsible, EmptyState, Spinner, StatTile, cx, money } from "@/ui";
import { SplitBanner } from "./SplitBanner";

export function Comparison({ caseId }: { caseId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["comparison", caseId],
    queryFn: () => tender.comparison(caseId),
  });

  if (isLoading) {
    return (
      <Card>
        <div className="px-5 py-8">
          <Spinner label="Сводим предложения…" />
        </div>
      </Card>
    );
  }

  if (!data?.analyzed) {
    return (
      <Card>
        <EmptyState
          title="Закупка ещё не разобрана"
          description="Запустите разбор — после него предложения поставщиков сведутся по позициям и станет видно, чья цена лучше."
        />
      </Card>
    );
  }

  // Позиций нет — человек должен понять почему, а не смотреть на пустоту.
  // Чаще всего причина одна из двух: в папке несколько разных закупок или
  // поставщики ещё не прислали предложений.
  if (!data.positions.length) {
    return (
      <div className="space-y-4">
        <SplitBanner caseId={caseId} />
        <Card>
          <EmptyState
            title="Сравнивать пока нечего"
            description={
              data.offers === 0
                ? "В закупке нет коммерческих предложений — только документы заказчика. Сравнение появится, когда поставщики пришлют цены."
                : "Предложения есть, но их позиции не сошлись по названиям. Откройте документы и проверьте состав."
            }
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Предложений" value={data.offers} hint="КП поставщиков" />
        <StatTile label="Позиций" value={data.positions.length} />
        <StatTile
          label="Дешевле всех"
          value={data.total_min ? money(data.total_min) : "—"}
          unit={data.total_min ? "₸" : undefined}
          tone="series-3"
        />
        <StatTile
          label="Дороже всех"
          value={data.total_max ? money(data.total_max) : "—"}
          unit={data.total_max ? "₸" : undefined}
          tone="series-2"
        />
      </div>

      {data.decision && (
        <Card title="Решение">
          <div className="space-y-3 px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              {data.decision.recommendation && (
                <Badge tone={toneOf(data.decision.recommendation)}>
                  {data.decision.recommendation}
                </Badge>
              )}
              {data.decision.recommended_bid && (
                <span className="text-sm text-ink">
                  наша цена{" "}
                  <strong className="font-semibold">
                    {money(data.decision.recommended_bid)} ₸
                  </strong>
                </span>
              )}
              {data.decision.expected_margin_percent != null && (
                <span className="text-sm text-ink-secondary">
                  маржа ≈ {data.decision.expected_margin_percent}%
                </span>
              )}
            </div>
            {data.decision.summary && (
              <p className="text-sm text-ink-secondary">{data.decision.summary}</p>
            )}
            {data.decision.blockers.length > 0 && (
              <ul className="space-y-1">
                {data.decision.blockers.map((item) => (
                  <li key={item} className="flex gap-2 text-sm text-ink">
                    <span aria-hidden className="text-critical">
                      ●
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      )}

      <Card title={`Позиции (${data.positions.length})`}>
        <div className="divide-y divide-hairline">
          {data.positions.map((position) => (
            <section key={position.name} className="px-5 py-4">
              <header className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-ink">{position.name}</h3>
                <div className="flex items-center gap-2 text-xs text-ink-muted">
                  <span>
                    {position.supplier_count}{" "}
                    {plural(position.supplier_count, "поставщик", "поставщика", "поставщиков")}
                  </span>
                  {position.spread_ratio != null && position.spread_ratio > 1.01 && (
                    <Badge tone={position.spread_ratio > 1.5 ? "warning" : "neutral"}>
                      разброс ×{position.spread_ratio.toFixed(2)}
                    </Badge>
                  )}
                </div>
              </header>

              {/* Ширины заданы жёстко: таблицы позиций независимы, и без этого
                  колонки в каждой встают по своему содержимому — столбец цен
                  съезжает от позиции к позиции, и сравнивать взглядом сверху
                  вниз становится нельзя. */}
              <table className="w-full table-fixed text-sm">
                <colgroup>
                  <col className="w-[34%]" />
                  <col className="w-[38%]" />
                  <col className="w-[12%]" />
                  <col className="w-[16%]" />
                </colgroup>
                <thead>
                  <tr className="text-left text-xs text-ink-muted">
                    <th className="pb-1.5 font-medium">Поставщик</th>
                    <th className="pb-1.5 font-medium">Что предложил</th>
                    <th className="pb-1.5 text-right font-medium">Кол-во</th>
                    <th className="pb-1.5 text-right font-medium">Цена за ед., ₸</th>
                  </tr>
                </thead>
                <tbody>
                  {position.quotes.map((quote, index) => (
                    <tr key={`${quote.supplier}-${index}`} className="align-top">
                      <td className="truncate py-1.5 pr-3">
                        <span
                          className={cx(
                            "inline-flex items-center gap-1.5",
                            quote.is_cheapest ? "font-medium text-ink" : "text-ink-secondary",
                          )}
                        >
                          {quote.is_cheapest && (
                            // Значок, а не только цвет: при дальтонизме
                            // подсветка строки неразличима.
                            <span aria-hidden className="text-good">
                              ▼
                            </span>
                          )}
                          {quote.supplier ?? "—"}
                          {quote.is_cheapest && <span className="sr-only">лучшая цена</span>}
                        </span>
                      </td>
                      <td
                        className="truncate py-1.5 pr-3 text-ink-muted"
                        title={quote.specification ?? undefined}
                      >
                        {quote.specification ?? "—"}
                      </td>
                      <td className="py-1.5 pr-3 text-right text-ink-secondary">
                        {quote.quantity ?? "—"} {quote.unit ?? ""}
                      </td>
                      <td
                        className={cx(
                          "py-1.5 text-right",
                          quote.is_cheapest ? "font-semibold text-good" : "text-ink",
                        )}
                      >
                        {quote.unit_price != null ? money(quote.unit_price) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
        </div>
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

      {data.requirements.length > 0 && (
        <Collapsible
          title="Что требует заказчик"
          count={data.requirements.length}
          hint="Эти пункты попадут в наше КП как подтверждение соответствия"
        >
          <ul className="divide-y divide-hairline">
            {data.requirements.map((item) => (
              <li key={item} className="px-5 py-2 text-sm text-ink-secondary">
                {item}
              </li>
            ))}
          </ul>
        </Collapsible>
      )}
    </div>
  );
}

function toneOf(recommendation: string) {
  if (recommendation.includes("участвовать") && !recommendation.includes("не")) return "good";
  if (recommendation.includes("не участвовать")) return "critical";
  return "warning";
}

function plural(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}
