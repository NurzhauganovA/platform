/**
 * Рабочий список: что смотреть сегодня.
 *
 * Один экран на все три раздела — SKStore, OMarket и тендерный отбор.
 * Устроены они одинаково, и сотрудник, который ходит во все, не должен
 * переучиваться на полпути.
 *
 * Порядок сверху вниз повторяет ход мысли. Сначала «всё ли готово» — если не
 * задан ключ или пуста база, остальное объяснять бессмысленно. Потом четыре
 * числа: сколько в работе, сколько стоит брать, сколько на этом заработаем.
 * Потом отбор и поиск. И только потом таблица — она большая, и загораживать
 * ею ответ на вопрос «есть ли вообще чем заняться» не стоит.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  worklists,
  type ColumnSet,
  type WorklistSlug,
  type Scope,
  type Worklist,
  type WorklistAction,
} from "@/api/worklist";
import type { Job } from "@/api/tender";
import { PageHeader } from "@/shell/AppShell";
import { Button, Card, Progress, Spinner, StatTile, cx, money } from "@/ui";
import { DetailPanel } from "./DetailPanel";
import { WorkTable } from "./WorkTable";
import { GLYPH, GLYPH_COLOR } from "./verdicts";
import {
  apply,
  clearAll,
  countValues,
  filterable,
  readFilters,
  without,
  writeFilter,
  type ColumnFilter,
  type Filterable,
  type FilterState,
} from "./filters";
import { summarise, type Tile } from "./summary";
import { TZ } from "./format";

/** Живой прогресс задачи. За минуты связь рвётся, и поток восстанавливается сам. */
function useJobStream(jobId: string | null, onDone: () => void) {
  const [job, setJob] = useState<Job | null>(null);
  const finished = useRef<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setJob(null);
    finished.current = null;

    const source = new EventSource(`/api/jobs/${jobId}/stream`, {
      withCredentials: true,
    });
    source.onmessage = (event) => {
      const data = JSON.parse(event.data) as Partial<Job>;
      setJob(
        (current) =>
          ({ ...(current ?? ({ id: jobId } as Job)), ...data }) as Job,
      );

      if (
        data.status &&
        ["succeeded", "failed", "cancelled"].includes(data.status)
      ) {
        source.close();
        if (finished.current !== data.status) {
          finished.current = data.status;
          onDone();
        }
      }
    };
    source.onerror = () => source.close();
    return () => source.close();
    // `onDone` намеренно не в зависимостях: он пересоздаётся на каждом
    // рендере, и поток пересоздавался бы вместе с ним — прогресс мигал бы.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return job;
}

export function WorklistPage({
  slug,
  title,
  subtitle,
  unit,
  emptyHint = "Данных пока нет.",
}: {
  slug: WorklistSlug;
  title: string;
  subtitle: string;
  /** Как называются строки: «закупов», «предзаказов». Для подписей к числам. */
  unit: string;
  /** Что делать, если список пуст, а кнопки «Обновить» в разделе нет. Знает
   *  это только сам раздел: общий экран не должен упоминать чужие команды. */
  emptyHint?: string;
}) {
  const client = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);

  // Отбор живёт в адресе, а не в памяти вкладки. Так его можно переслать
  // коллеге — «посмотри вот эти четыре» — и он откроет ровно тот же список,
  // а не будет собирать фильтры заново с чужих слов.
  const [params, setParams] = useSearchParams();
  const scope = (params.get("scope") as Scope) ?? "focus";
  const columns = (params.get("columns") as ColumnSet) ?? "key";
  const filter = params.get("q") ?? "";
  const tones = useMemo(
    () => new Set((params.get("tone") ?? "").split(",").filter(Boolean)),
    [params],
  );
  const openId = params.get("open");
  const filters = useMemo(() => readFilters(params), [params]);

  function update(patch: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    // `replace`: отбор — не шаг в истории. Иначе «назад» после десяти
    // нажатий отматывает фильтры по одному вместо возврата на прошлый экран.
    setParams(next, { replace: true });
  }

  const setScope = (value: Scope) =>
    update({ scope: value === "focus" ? null : value });
  const setColumns = (value: ColumnSet) =>
    update({ columns: value === "key" ? null : value });
  const setFilter = (value: string) => update({ q: value || null });
  const setTones = (value: Set<string>) =>
    update({ tone: value.size ? [...value].join(",") : null });
  const open = (id: string | null) => update({ open: id });
  const setFilterFor = (key: string, next: ColumnFilter | null) =>
    update(writeFilter(key, next));

  const { data, isLoading, isError, error } = useQuery({
    queryKey: [slug, "worklist"],
    queryFn: () => worklists.worklist(slug),
  });

  const refresh = () => {
    client.invalidateQueries({ queryKey: [slug] });
  };

  const job = useJobStream(jobId, refresh);
  const running = job?.status === "queued" || job?.status === "running";

  const sync = useMutation({
    mutationFn: () => worklists.sync(slug),
    onSuccess: (started) => setJobId(started.job_id),
  });

  const analyze = useMutation({
    mutationFn: () => worklists.analyze(slug),
    onSuccess: (started) => setJobId(started.job_id),
  });

  const stop = useMutation({
    mutationFn: () => worklists.cancel(jobId ?? ""),
  });

  // Что показывать, решает сервер. Кнопки приходят списком: у тендерного
  // отбора нет ни обновления, ни пересчёта — папки разбирают на машине
  // тендерщика, — а пересчёт у площадок виден только тому, кто платит.
  // Решать это второй раз здесь значило бы завести второе правило, и
  // разошлись бы они на кнопке, которая отвечает 403.
  const can = (action: WorklistAction) =>
    Boolean(data?.actions.includes(action));
  const seesMoney = Boolean(data?.columns.some((column) => column.sensitive));

  // Отбор считается здесь, а не в таблице: по нему же строятся легенда и
  // итог снизу. Посчитай его в трёх местах — и однажды они разойдутся.
  const inScope = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    // Одни цифры в поиске — это номер строки, а не кусок названия. Так им и
    // пользуются: коллега сказал «сорок вторая», её набирают и находят. Ровно,
    // а не «содержит»: иначе «4» вытащила бы четвёртую, сороковые и все
    // четырёхсотые разом.
    const wanted = /^\d+$/.test(needle) ? Number(needle) : null;
    return (data?.rows ?? []).filter(
      (row) =>
        (scope === "all" || row.focus) &&
        (!needle ||
          row.number === wanted ||
          row.cells.some((cell) => cell.text.toLowerCase().includes(needle))),
    );
  }, [data?.rows, filter, scope]);

  // Порядок отбора: поиск и область, потом цвет, потом колонки. Каждый
  // счётчик считается по всему, кроме себя самого, — иначе выбранное значение
  // показывало бы «столько же» и отбор выглядел бы неработающим.
  const byTone = useMemo(
    () => (tones.size ? inScope.filter((row) => tones.has(row.tone)) : inScope),
    [inScope, tones],
  );

  const visible = useMemo(
    () => (data ? apply(byTone, data.columns, filters) : byTone),
    [byTone, data, filters],
  );

  /** Для легенды: всё, кроме отбора по самому цвету. */
  const forLegend = useMemo(
    () => (data ? apply(inScope, data.columns, filters) : inScope),
    [inScope, data, filters],
  );

  // Что вообще можно отобрать — по самим данным, а не по списку заголовков:
  // раздел, который добавят следующим, получит фильтры сам.
  //
  // Состав значений и границы диапазонов берутся до отбора по колонкам:
  // иначе снятое значение исчезало бы из списка и вернуть его было бы нечем,
  // а «от и до» схлопывались бы после каждого нажатия.
  const targets = useMemo(() => {
    if (!data) return new Map<string, Filterable>();
    return new Map(
      filterable({ ...data, rows: byTone }).map((item) => {
        if (item.kind !== "values") return [item.column.key, item];
        const counts = countValues(
          apply(byTone, data.columns, without(filters, item.column.key)),
          item.index,
        );
        return [
          item.column.key,
          {
            ...item,
            options: item.options.map((option) => ({
              ...option,
              count: counts.get(option.value) ?? 0,
            })),
          },
        ];
      }),
    );
  }, [data, byTone, filters]);

  const marginColumn = data?.columns.findIndex(
    (column) =>
      column.sensitive &&
      column.format === "money" &&
      /всего|₸$/i.test(column.title),
  );
  const selectedMargin =
    seesMoney && marginColumn != null && marginColumn >= 0
      ? visible.reduce(
          (sum, row) => sum + (row.cells[marginColumn]?.number ?? 0),
          0,
        )
      : null;

  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex items-center gap-2">
            {can("sync") && (
              <Button
                onClick={() => sync.mutate()}
                disabled={running || sync.isPending}
              >
                Обновить данные
              </Button>
            )}
            {can("analyze") && (
              <Button
                variant="primary"
                onClick={() => analyze.mutate()}
                disabled={running || analyze.isPending}
              >
                Пересчитать
              </Button>
            )}
            {can("export") && (
              <a href={worklists.exportUrl(slug)} download>
                <Button>Скачать Excel</Button>
              </a>
            )}
          </div>
        }
      />

      <div className="space-y-4 px-8 py-6">
        {job && running && (
          <Card className="px-5 py-3.5">
            <div className="flex items-center justify-between gap-4">
              {/* Подпись приходит от задачи и называет числа: «разобрано 340
                  из 1121». Без них полоска на 0% отвечает «работаем» на
                  вопрос «сколько ещё ждать» и «это отобранные или все». */}
              <Spinner label={job.note || "Работаем…"} />
              <div className="flex shrink-0 items-center gap-3">
                <span className="text-xs text-ink-muted">{job.percent}%</span>
                <Button
                  variant="ghost"
                  onClick={() => stop.mutate()}
                  disabled={stop.isPending}
                  title="Прервать прогон на ближайшем закупе"
                >
                  {stop.isPending ? "Останавливаем…" : "Остановить"}
                </Button>
              </div>
            </div>
            <div className="mt-2.5">
              <Progress percent={job.percent} />
            </div>
          </Card>
        )}

        {job && job.status === "cancelled" && (
          <Card className="px-5 py-3.5">
            <div className="text-sm text-ink">
              Остановлено. Посчитанное до остановки сохранено — прогон
              продолжится с того же места.
            </div>
          </Card>
        )}

        {job && job.status === "failed" && (
          <Card className="border-critical/40 bg-critical/10 px-5 py-3.5">
            <div className="text-sm font-medium text-ink">✕ Не получилось</div>
            <p className="mt-1 text-sm text-ink-secondary">{job.error}</p>
          </Card>
        )}

        {job && job.status === "succeeded" && !running && (
          <Finished job={job} unit={unit} />
        )}

        {data && (
          <Tiles
            tiles={summarise({
              rows: visible,
              total: data.rows.length,
              columns: data.columns,
              unit,
              goodLabel:
                data.legend.find((item) => item.tone === "good")?.title ?? "",
            })}
          />
        )}

        {data && (
          <ActiveFilters
            filters={filters}
            columns={data.columns}
            onDrop={(key) => update(writeFilter(key, null))}
            onClear={() => update(clearAll(filters))}
          />
        )}

        {data && data.rows.length > 0 && (
          <Legend
            legend={data.legend}
            rows={forLegend}
            chosen={tones}
            onChange={setTones}
          />
        )}

        <Card
          title={
            data
              ? `${data.sheet} — ${visible.length} из ${data.total}`
              : "Список"
          }
          action={
            <div className="flex items-center gap-2">
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Найти по номеру, названию или заказчику…"
                className="w-64 rounded-[8px] border border-baseline bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted"
              />
              <Switch<Scope>
                value={scope}
                onChange={setScope}
                options={[
                  { value: "focus", title: "Только нужное" },
                  { value: "all", title: "Все строки" },
                ]}
              />
              <Switch<ColumnSet>
                value={columns}
                onChange={setColumns}
                options={[
                  { value: "key", title: "Главное" },
                  { value: "all", title: "Все колонки" },
                ]}
              />
            </div>
          }
        >
          {isLoading ? (
            <div className="px-5 py-10">
              <Spinner label="Собираем список…" />
            </div>
          ) : isError ? (
            <div className="px-5 py-10 text-center">
              <p className="text-sm font-medium text-ink">
                Данные пока недоступны
              </p>
              <p className="mt-1 text-sm text-ink-muted">
                {error instanceof Error
                  ? error.message
                  : "Попробуйте обновить данные"}
              </p>
            </div>
          ) : data && visible.length === 0 ? (
            <Empty
              analyzed={data.analyzed}
              scope={scope}
              unit={unit}
              expired={data.expired}
              filter={filter}
              tones={tones}
              actions={data.actions}
              hint={emptyHint}
            />
          ) : (
            data && (
              <>
                <WorkTable
                  data={data}
                  rows={visible}
                  columns={columns}
                  onOpen={(id) => open(id)}
                  openId={openId}
                  filters={filters}
                  targets={targets}
                  onFilter={setFilterFor}
                />
                {selectedMargin != null && visible.length > 0 && (
                  <div className="flex items-center justify-between gap-4 border-t border-hairline bg-plane px-5 py-2.5 text-sm">
                    <span className="text-ink-secondary">
                      Показано {visible.length}{" "}
                      {plural(visible.length, "строка", "строки", "строк")}
                    </span>
                    <span className="text-ink">
                      Заработаем на них{" "}
                      <span className="font-semibold">
                        {money(selectedMargin)} ₸
                      </span>
                    </span>
                  </div>
                )}
                {data.expired > 0 && scope === "focus" && can("sync") && (
                  <p className="border-t border-hairline px-5 py-2.5 text-xs text-ink-muted">
                    Скрыто {data.expired}{" "}
                    {plural(data.expired, "строка", "строки", "строк")} с
                    истёкшим приёмом — сделать с ними уже нечего. Из базы они не
                    удаляются: по ним видно, что мы пропустили и почём уходило.
                    Показать —{" "}
                    <button
                      onClick={() => setScope("all")}
                      className="underline underline-offset-2 hover:text-ink"
                    >
                      «Все строки»
                    </button>
                    . Своё, где мы участвуем, остаётся в списке и после срока.
                  </p>
                )}
                {data.hidden_columns > 0 && (
                  <p className="border-t border-hairline px-5 py-2.5 text-xs text-ink-muted">
                    Ещё {data.hidden_columns}{" "}
                    {plural(
                      data.hidden_columns,
                      "колонка",
                      "колонки",
                      "колонок",
                    )}{" "}
                    с себестоимостью и маржой — их видит тендерщик.
                  </p>
                )}
              </>
            )
          )}
        </Card>
      </div>

      {openId && (
        <DetailPanel
          slug={slug}
          id={openId}
          onClose={() => open(null)}
          onOpen={open}
        />
      )}
    </>
  );
}

/** Переключатель из двух-трёх положений. Выбранное отмечено не только цветом:
 *  `aria-pressed` читается озвучкой, а фон подкреплён жирностью. */
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

/**
 * Легенда: что означает цвет — и заодно отбор по нему.
 *
 * Два дела одной строкой намеренно. Легенда, которая только объясняет, через
 * неделю перестаёт читаться; та, по которой ещё и щёлкают, остаётся на виду.
 *
 * Рядом с цветом всегда значок своей формы и слово. Цвет сам по себе смысла
 * не несёт: при дальтонизме «участвовать» и «не участвовать» неразличимы.
 */
function Legend({
  legend,
  rows,
  chosen,
  onChange,
}: {
  /** Слова этого раздела. Приходят с сервера: «участвовать» у площадки и
   *  «брать» у тендерного отбора — это одно и то же решение разными словами,
   *  и подписывать оба одним списком в браузере значит однажды соврать. */
  legend: Worklist["legend"];
  rows: Worklist["rows"];
  chosen: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.tone, (counts.get(row.tone) ?? 0) + 1);

  const available = legend.filter((item) => counts.get(item.tone));
  if (!available.length) return null;

  function toggle(tone: string) {
    const next = new Set(chosen);
    if (next.has(tone)) next.delete(tone);
    else next.add(tone);
    onChange(next);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-xs text-ink-muted">Цвет строки:</span>
      {available.map((item) => {
        const active = chosen.has(item.tone);
        return (
          <button
            key={item.tone}
            onClick={() => toggle(item.tone)}
            aria-pressed={active}
            title={`${item.title} — ${item.hint}. Щёлкните, чтобы оставить только такие`}
            className={cx(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition",
              active
                ? "border-series-1 bg-series-1/10 font-semibold text-series-1"
                : "border-hairline font-medium text-ink-secondary hover:border-baseline hover:text-ink",
            )}
          >
            <span
              aria-hidden
              className={cx("text-[13px] leading-none", GLYPH_COLOR[item.tone])}
            >
              {GLYPH[item.tone]}
            </span>
            {item.title}
            <span className="text-ink-muted">{counts.get(item.tone)}</span>
            {/* Галочка, а не только цвет рамки: нажатое состояние должно
                читаться и без цвета. */}
            {active && <span aria-hidden>✓</span>}
          </button>
        );
      })}
      {chosen.size > 0 && (
        <button
          onClick={() => onChange(new Set())}
          className="text-xs text-ink-muted underline underline-offset-2 hover:text-ink"
        >
          сбросить
        </button>
      )}
    </div>
  );
}

function Tiles({ tiles }: { tiles: Tile[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {tiles.map((tile) => (
        <StatTile
          key={tile.label}
          label={tile.label}
          value={tile.value}
          unit={tile.unit}
          hint={tile.hint}
          tone={tile.tone}
        />
      ))}
    </div>
  );
}

/**
 * Что сейчас отобрано — метками над таблицей.
 *
 * Фильтр стоит в шапке колонки, и это удобно ставить, но не видно, когда
 * колонок семнадцать и половина из них за краем экрана. Строка «показано 12
 * из 265» без объяснения, почему двенадцать, читается как поломка: человек
 * ищет пропавшие строки, а не снимает фильтр, о котором забыл.
 */
function ActiveFilters({
  filters,
  columns,
  onDrop,
  onClear,
}: {
  filters: FilterState;
  columns: Worklist["columns"];
  onDrop: (key: string) => void;
  onClear: () => void;
}) {
  if (!filters.size) return null;
  const titleOf = (key: string) =>
    columns.find((column) => column.key === key)?.title ?? key;
  const formatOf = (key: string) =>
    columns.find((column) => column.key === key)?.format ?? "text";
  // Знак процента — по роли, а не по формату: в книге отбора маржа записана
  // обычным числом («116,3»), и по формату её от количества не отличить.
  const roleOf = (key: string) =>
    columns.find((column) => column.key === key)?.role ?? "";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-xs text-ink-muted">Отобрано:</span>
      {[...filters].map(([key, filter]) => (
        <button
          key={key}
          onClick={() => onDrop(key)}
          title="Снять этот отбор"
          className="inline-flex max-w-xs items-center gap-1.5 rounded-full border border-series-1 bg-series-1/10 px-3 py-1 text-xs font-medium text-series-1 transition hover:bg-series-1/15"
        >
          <span className="truncate">
            {titleOf(key)}: {describe(filter, formatOf(key), roleOf(key))}
          </span>
          <span aria-hidden>✕</span>
        </button>
      ))}
      <button
        onClick={onClear}
        className="text-xs text-ink-muted underline underline-offset-2 hover:text-ink"
      >
        снять всё
      </button>
    </div>
  );
}

/** Условие словами — то, что читается в метке. */
function describe(filter: ColumnFilter, format: string, role: string): string {
  if (filter.kind === "values") {
    const values = [...filter.values];
    if (values.length <= 2) return values.join(", ");
    return `${values[0]} и ещё ${values.length - 1}`;
  }
  const show = (value: number) =>
    format === "datetime"
      ? new Date(value).toLocaleDateString("ru-RU", { timeZone: TZ })
      : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(
          value,
        );
  const suffix = format === "percent" || role === "margin" ? "%" : "";
  if (filter.min != null && filter.max != null)
    return `${show(filter.min)}–${show(filter.max)}${suffix}`;
  if (filter.min != null) return `от ${show(filter.min)}${suffix}`;
  return `до ${show(filter.max as number)}${suffix}`;
}

/** Итог прогона словами: что именно изменилось, а не «готово».
 *
 * Источники выгружаются независимо — упавший не должен утаскивать за собой
 * остальные, — и поэтому прогон заканчивается успехом даже когда закупы не
 * доехали. Складывать их в одно число нельзя: «получено записей: 766» зелёной
 * галочкой при недоступном кабинете читается как «всё хорошо», человек ждёт
 * новых закупов и не понимает, почему список прежний.
 */
function Finished({ job, unit }: { job: Job; unit: string }) {
  const result = (job.result ?? {}) as {
    records?: number;
    by_source?: Record<string, number>;
    errors?: string[];
    reason?: string;
    analyzed_new?: number;
    bargains?: number;
    preorders?: number;
    market_searched?: number;
    market_priced?: number;
  };
  const errors = result.errors ?? [];
  const bySource = Object.entries(result.by_source ?? {});

  const parts: string[] = [];
  if (job.kind === "sync") {
    // По источникам, а не одним числом: спрашивают «пришли ли закупы»,
    // а не «сколько всего записей».
    parts.push(
      bySource.length
        ? bySource.map(([name, count]) => `${name}: ${count}`).join(" · ")
        : `получено записей: ${result.records ?? 0}`,
    );
    // Разбор идёт только по новым, и сказать об этом надо словами: «0» тут
    // означает «нового не появилось», а не «разбор не отработал».
    if (result.analyzed_new !== undefined)
      parts.push(
        result.analyzed_new
          ? `разобрано новых: ${result.analyzed_new}`
          : "новых закупов нет",
      );
  } else {
    const counted = result.bargains ?? result.preorders ?? 0;
    parts.push(`пересчитано ${counted} ${unit}`);
    if (result.market_searched)
      parts.push(`найдено на рынке: ${result.market_priced ?? 0}`);
  }
  if (result.reason) parts.push(result.reason);

  const failed = errors.length > 0;
  return (
    <Card
      className={cx(
        "px-5 py-3",
        failed
          ? "border-warning/40 bg-warning/10"
          : "border-good/40 bg-good/10",
      )}
    >
      <div className="flex items-start gap-2 text-sm">
        <span aria-hidden className={failed ? "text-warning" : "text-good"}>
          {failed ? "⚠" : "✓"}
        </span>
        <div className="space-y-1">
          <div className="text-ink">
            {/* Значок цветом не ограничивается: при дальтонизме зелёный и
                жёлтый неразличимы, а разница здесь — между «данные пришли»
                и «половина не пришла». */}
            {failed && (
              <span className="font-medium">Выгрузилось не всё. </span>
            )}
            {parts.join(" · ")}
          </div>
          {errors.map((message) => (
            <div key={message} className="text-ink-secondary">
              {message}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function Empty({
  analyzed,
  scope,
  unit,
  expired,
  filter,
  tones,
  actions,
  hint,
}: {
  analyzed?: boolean;
  scope: Scope;
  unit: string;
  expired: number;
  filter: string;
  tones: Set<string>;
  /** Что в этом разделе вообще можно нажать. Совет «нажмите Обновить» там,
   *  где такой кнопки нет, отправляет человека искать её по экрану. */
  actions: WorklistAction[];
  /** Что делать, когда обновлять нечем. Раздел знает это про себя сам:
   *  общий экран не должен упоминать ни площадку, ни команду ядра. */
  hint: string;
}) {
  // Пустой список — это несколько разных ответов, и путать их нельзя.
  // «Работы нет», «данные устарели», «ещё не считали» и «всё отсеялось»
  // требуют от человека совершенно разных действий.
  const sync = actions.includes("sync")
    ? " Нажмите «Обновить данные»."
    : ` ${hint}`;
  const message = filter
    ? `По запросу «${filter}» ничего не нашлось.`
    : tones.size
      ? "Под выбранное решение ничего не подходит."
      : expired > 0 && scope === "focus"
        ? `У всех ${expired} ${plural(expired, "строки", "строк", "строк")} приём уже закончился — свежих нет.${sync}`
        : analyzed === false
          ? actions.includes("analyze")
            ? "Данные есть, но себестоимость ещё не считали — нажмите «Пересчитать»."
            : "Данные есть, но себестоимость ещё не считали."
          : scope === "focus"
            ? `Ничего подходящего. Посмотрите «Все строки» — там ${unit}, которые отсеялись.`
            : `Пока пусто.${sync}`;

  return (
    <div className="px-5 py-12 text-center text-sm text-ink-muted">
      {message}
    </div>
  );
}

function plural(count: number, one: string, few: string, many: string): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return many;
  const ones = count % 10;
  if (ones === 1) return one;
  if (ones >= 2 && ones <= 4) return few;
  return many;
}
