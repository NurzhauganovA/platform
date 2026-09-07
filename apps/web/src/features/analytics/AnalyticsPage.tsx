/**
 * Аналитика раздела: где наши деньги, в разрезе.
 *
 * Один экран на все три раздела, как и рабочий список: устроены они одинаково,
 * а что именно считать, подсказывают роли колонок с сервера. Раздел, который
 * добавят следующим, получит аналитику сам.
 *
 * Главный разрез — категория, и это не вкусовщина: вопрос «в чём мы сильны»
 * задают чаще остальных, а отдел силён не во всём. Но разрез переключается:
 * заказчик отвечает на «сколько мы возим Акбастау», признак закупки — на «где
 * деньги, в товарах или в услугах».
 *
 * Данные берутся из того же ответа, что рисует таблицу, и лежат в общем кэше
 * запросов: переход между списком и аналитикой мгновенный, второго мегабайта
 * по сети не идёт.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { worklists, type WorklistSlug } from "@/api/worklist";
import { PageHeader } from "@/shell/AppShell";
import { Card, EmptyState, Page, Spinner, cx, money } from "@/ui";
import {
  defaultSlice,
  indexOfRole,
  slices,
  sliceable,
  type Slice,
} from "./aggregate";

export function AnalyticsPage({
  slug,
  title,
}: {
  slug: WorklistSlug;
  title: string;
}) {
  const [params, setParams] = useSearchParams();
  const [scope, setScope] = useState<"focus" | "all">("focus");

  // Тот же ключ, что у рабочего списка: переход между списком и аналитикой
  // раздела не должен тянуть по сети то, что уже лежит в кэше вкладки.
  const { data, isLoading, isError, error } = useQuery({
    queryKey: [slug, "worklist", scope],
    queryFn: () => worklists.worklist(slug, scope),
    placeholderData: (previous) => previous,
  });

  const cuts = useMemo(() => (data ? sliceable(data) : []), [data]);
  const by = params.get("by") ?? (data ? defaultSlice(data) : "");
  const setBy = (value: string) => {
    const next = new URLSearchParams(params);
    next.set("by", value);
    setParams(next, { replace: true });
  };

  // Отбор по области делает сервер — он и присылает только нужное.
  const rows = useMemo(() => data?.rows ?? [], [data]);

  const cut = useMemo(
    () => (data && by ? slices(data, rows, by) : []),
    [data, rows, by],
  );

  // Деньги показываем только тому, кому их показал сервер: он уже вырезал
  // колонки по правам, и спрашивать роль второй раз здесь значило бы завести
  // второе правило.
  const seesMoney = Boolean(data?.columns.some((column) => column.sensitive));
  const hasTotal = Boolean(data && indexOfRole(data.columns, "total") >= 0);
  // Заголовок берётся из колонки как есть, без склонения: «по категория»
  // читается как ошибка, а склонять русские слова в интерфейсе — это
  // словарь исключений ради одной подписи.
  const cutTitle = cuts.find((column) => column.key === by)?.title ?? "—";

  return (
    <>
      <PageHeader
        title={`Аналитика — ${title}`}
        subtitle="Где наши деньги: по категориям, заказчикам и признакам закупки"
        action={
          <Switch<"focus" | "all">
            value={scope}
            onChange={setScope}
            options={[
              { value: "focus", title: "Только нужное" },
              { value: "all", title: "Все строки" },
            ]}
          />
        }
      />

      <Page>
        {isLoading && (
          <Card className="px-5 py-10">
            <Spinner label="Считаем…" />
          </Card>
        )}

        {isError && (
          <Card>
            <EmptyState
              title="Данные пока недоступны"
              description={
                error instanceof Error ? error.message : "Попробуйте позже"
              }
            />
          </Card>
        )}

        {data && (
          <>
            <Card
              title={`Всё по разрезу: ${cutTitle.toLowerCase()} — ${cut.length}`}
              action={
                <div className="flex flex-wrap items-center gap-1.5">
                  {cuts.map((column) => (
                    <button
                      key={column.key}
                      onClick={() => setBy(column.key)}
                      aria-pressed={column.key === by}
                      className={cx(
                        // Тот же вид, что у вкладок на остальных экранах:
                        // одно и то же действие не должно выглядеть на
                        // каждой странице по-своему.
                        "rounded-[8px] px-3 py-1.5 text-sm transition",
                        column.key === by
                          ? "bg-ink text-surface"
                          : "text-ink-secondary hover:bg-plane",
                      )}
                    >
                      {column.title}
                    </button>
                  ))}
                </div>
              }
            >
              <SliceTable
                slices={cut}
                cutTitle={cutTitle}
                hasTotal={hasTotal}
                seesMoney={seesMoney}
              />
            </Card>
          </>
        )}
      </Page>
    </>
  );
}

/**
 * Тот же разрез числами.
 *
 * График отвечает на «где больше», таблица — на «насколько именно». Без неё
 * пришлось бы наводить курсор на каждый столбик и запоминать.
 */
function SliceTable({
  slices,
  cutTitle,
  hasTotal,
  seesMoney,
}: {
  slices: Slice[];
  cutTitle: string;
  hasTotal: boolean;
  seesMoney: boolean;
}) {
  if (!slices.length) {
    return (
      <div className="px-5 py-10 text-center text-sm text-ink-muted">
        Нечего разрезать
      </div>
    );
  }
  const biggest = Math.max(...slices.map((item) => item.total ?? item.rows));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-hairline text-xs text-ink-secondary">
            {/* Номер: разрезов бывает под сотню, и место строки в порядке
                убывания — это и есть ответ на «какая категория главная». */}
            <th className="w-12 px-3 py-2 text-right font-medium">№</th>
            <th className="px-5 py-2 text-left font-medium">{cutTitle}</th>
            <th className="px-3 py-2 text-right font-medium">Строк</th>
            <th className="px-3 py-2 text-right font-medium">Брать</th>
            {hasTotal && (
              <th className="px-3 py-2 text-right font-medium">Объём, ₸</th>
            )}
            {seesMoney && (
              <th className="px-3 py-2 text-right font-medium">
                Себестоимость, ₸
              </th>
            )}
            {seesMoney && (
              <th className="px-3 py-2 text-right font-medium">Заработок, ₸</th>
            )}
            <th className="px-3 py-2 text-right font-medium">Маржа</th>
            <th className="px-5 py-2 text-right font-medium">Оценено</th>
          </tr>
        </thead>
        <tbody>
          {slices.map((item, position) => (
            <tr
              key={item.name}
              className="border-b border-hairline last:border-0 hover:bg-plane"
            >
              <td className="px-3 py-1.5 text-right align-top tabular-nums text-ink-muted">
                {position + 1}
              </td>
              <td className="px-5 py-1.5">
                {/* Полоска под названием: доля этого разреза читается боковым
                    зрением, без сравнения чисел между собой. */}
                <div className="truncate text-ink" title={item.name}>
                  {item.name}
                </div>
                <div className="mt-1 h-1 w-full rounded-full bg-plane">
                  <div
                    className="h-1 rounded-full bg-series-1/60"
                    style={{
                      width: `${Math.round(((item.total ?? item.rows) / (biggest || 1)) * 100)}%`,
                    }}
                  />
                </div>
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-ink">
                {item.rows}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                <span className={item.good ? "text-good" : "text-ink-muted"}>
                  {item.good}
                </span>
              </td>
              {hasTotal && (
                <td className="px-3 py-1.5 text-right tabular-nums text-ink">
                  {item.total == null ? "—" : money(item.total)}
                </td>
              )}
              {seesMoney && (
                <td className="px-3 py-1.5 text-right tabular-nums text-ink">
                  {item.cost == null ? "—" : money(item.cost)}
                </td>
              )}
              {seesMoney && (
                <td className="px-3 py-1.5 text-right tabular-nums text-ink">
                  {item.profit == null ? "—" : money(item.profit)}
                </td>
              )}
              <td className="px-3 py-1.5 text-right tabular-nums text-ink">
                {item.margin == null ? "—" : `${item.margin.toFixed(1)} %`}
              </td>
              <td className="px-5 py-1.5 text-right tabular-nums text-ink-secondary">
                {item.priced} из {item.rows}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Switch<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (next: T) => void;
  options: { value: T; title: string }[];
}) {
  return (
    <div className="flex rounded-[8px] border border-baseline p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={cx(
            "rounded-[6px] px-2.5 py-1 text-xs transition",
            value === option.value
              ? "bg-series-1/10 font-semibold text-series-1"
              : "font-medium text-ink-secondary hover:text-ink",
          )}
        >
          {option.title}
        </button>
      ))}
    </div>
  );
}
