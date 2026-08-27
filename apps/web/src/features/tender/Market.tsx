/**
 * Что нашлось на рынках.
 *
 * Ради этого экрана поиск и запускают. Находка без площадки, цены и ссылки —
 * не находка, а обещание: менеджер идёт с этой строкой звонить, и всё, чего
 * в ней не хватает, ему придётся искать заново.
 *
 * Сортировка по марже, а не по цене. Дешёвое предложение из Китая с доставкой
 * в два месяца проигрывает казахстанскому, которое дороже на десять процентов:
 * сравнивать надо то, что останется у нас, а не ценник на витрине.
 */

import { tender, type CaseComparison } from "@/api/tender";
import { Badge, Card, EmptyState, StatTile, cx, money } from "@/ui";

// Ключи в кавычках: это не наши имена, а данные ядра. Страну оно возвращает
// по-русски, и переписать её здесь на латиницу значит перестать узнавать то,
// что приходит.
const FLAGS = new Map([
  ["Казахстан", "KZ"],
  ["Кыргызстан", "KG"],
  ["Россия", "RU"],
  ["Китай", "CN"],
  ["Узбекистан", "UZ"],
]);

export function Market({ data }: { data: CaseComparison }) {
  const market = data.market;

  if (!market?.searched) {
    return (
      <Card>
        <EmptyState
          title="Поиск на рынках ещё не запускали"
          description="Он покажет, где купить позиции закупки и почём: площадки Казахстана, Кыргызстана, России, Китая и Узбекистана. Отсюда берётся наша себестоимость — до неё маржа остаётся догадкой."
        />
      </Card>
    );
  }

  if (!market.findings.length) {
    return (
      <Card>
        <EmptyState
          title="На площадках ничего не нашлось"
          description="Так бывает с промышленными запчастями и работами: их не продают в розницу. Цену придётся запрашивать у производителя напрямую."
        />
      </Card>
    );
  }

  const viable = market.findings.filter(
    (item) => (item.margin_percent ?? 0) > 0,
  );
  const best = market.findings[0];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label="Найдено"
          value={market.findings.length}
          hint="предложений на рынке"
        />
        <StatTile label="Окупается" value={viable.length} tone="series-3" />
        <StatTile
          label="Лучшая маржа"
          value={best?.margin_percent != null ? `${best.margin_percent}` : "—"}
          unit={best?.margin_percent != null ? "%" : undefined}
          hint={best?.position?.slice(0, 34)}
          tone="good"
        />
        <StatTile
          label="Заработок"
          value={market.total_margin ? money(market.total_margin) : "—"}
          unit={market.total_margin ? "₸" : undefined}
          hint="по всем позициям"
          tone="good"
        />
      </div>

      {Object.keys(market.by_country).length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-muted">Где искали:</span>
          {Object.entries(market.by_country).map(([country, count]) => (
            <Badge key={country}>
              {country} · {count}
            </Badge>
          ))}
        </div>
      )}

      <Card title={`Где купить (${market.findings.length})`}>
        <div className="divide-y divide-hairline">
          {market.findings.map((finding, index) => (
            <article key={`${finding.url}-${index}`} className="px-5 py-3.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="min-w-0 text-sm font-medium text-ink">
                  {finding.position}
                </h3>
                <div className="flex items-center gap-2">
                  {!finding.matches_spec && (
                    <Badge tone="critical">
                      <span aria-hidden>✕</span> не проходит по ТЗ
                    </Badge>
                  )}
                  {finding.margin_percent != null && (
                    <span
                      className={cx(
                        "text-sm font-semibold",
                        finding.margin_percent >= 15
                          ? "text-good"
                          : "text-ink-secondary",
                      )}
                    >
                      маржа {finding.margin_percent}%
                    </span>
                  )}
                </div>
              </div>

              {finding.title && (
                <p
                  className="mt-0.5 truncate text-sm text-ink-secondary"
                  title={finding.title}
                >
                  {finding.title}
                </p>
              )}

              <dl className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm">
                <div className="flex items-baseline gap-1.5">
                  <dt className="text-xs text-ink-muted">
                    {FLAGS.get(finding.country) ?? ""} {finding.country}
                  </dt>
                  <dd className="text-ink">{finding.marketplace}</dd>
                </div>
                {finding.supplier && (
                  <div className="flex items-baseline gap-1.5">
                    <dt className="text-xs text-ink-muted">поставщик</dt>
                    <dd className="text-ink">{finding.supplier}</dd>
                  </div>
                )}
                {finding.price_kzt != null && (
                  <div className="flex items-baseline gap-1.5">
                    <dt className="text-xs text-ink-muted">цена</dt>
                    <dd className="font-medium text-ink">
                      {money(finding.price_kzt)} ₸
                    </dd>
                  </div>
                )}
                {finding.landed_cost != null && (
                  <div className="flex items-baseline gap-1.5">
                    <dt className="text-xs text-ink-muted">с доставкой</dt>
                    <dd className="text-ink">{money(finding.landed_cost)} ₸</dd>
                  </div>
                )}
                {finding.delivery_days != null && (
                  <div className="flex items-baseline gap-1.5">
                    <dt className="text-xs text-ink-muted">срок</dt>
                    <dd className="text-ink">{finding.delivery_days} дн.</dd>
                  </div>
                )}
                {finding.min_order && (
                  <div className="flex items-baseline gap-1.5">
                    <dt className="text-xs text-ink-muted">от</dt>
                    <dd className="text-ink">{finding.min_order}</dd>
                  </div>
                )}
              </dl>

              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                {finding.url && (
                  <a
                    href={finding.url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate text-series-1 hover:underline"
                  >
                    {shorten(finding.url)}
                  </a>
                )}
                {finding.contact && (
                  <span className="text-ink-secondary">
                    <span className="text-xs text-ink-muted">связаться: </span>
                    {finding.contact}
                  </span>
                )}
              </div>

              {!finding.matches_spec && finding.match_note && (
                <p className="mt-1.5 text-xs text-critical">
                  {finding.match_note}
                </p>
              )}
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}

function shorten(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    return parsed.host + (path.length > 30 ? path.slice(0, 30) + "…" : path);
  } catch {
    return url;
  }
}

export { tender };
