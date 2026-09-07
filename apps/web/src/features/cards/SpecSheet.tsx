/**
 * Разбор технической спецификации таблицей.
 *
 * Заменяет двадцать минут ручной раскладки на лот. Спецификация приходит
 * сплошным текстом, где требования к процессору, памяти и монитору идут подряд
 * через маркеры списка; работать с ней нельзя, пока не разложишь по предметам.
 *
 * Три первых столбца собирает модель, остальные заводят люди — под цену, нашу
 * спецификацию, ссылку на поставщика. Разница сказана один раз над таблицей:
 * подпись под каждым заголовком повторяла одно и то же пять раз подряд и
 * съедала строку в шапке. Свои столбцы пересборка не трогает.
 *
 * Правится всё: значение в ячейке, заголовок столбца, ширина, порядок строк.
 * В спецификации нет блока питания, а поставить его надо — это обычный ход
 * работы, а не исключение.
 *
 * Сохранение отложенное. Ячейку правят посимвольно, и запрос на каждое
 * нажатие клавиши — это сотня запросов на строку и таблица, которая тормозит
 * ровно там, где человек печатает.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { sheetApi, type Card, type Sheet, type SheetColumn } from "@/api/cards";
import { worklists, type SpecFile, type WorklistSlug } from "@/api/worklist";
import { ApiError } from "@/api/client";
import { useJobStream, type JobRun } from "@/api/jobs";
import { Button, Card as Panel, Progress, Spinner, cx } from "@/ui";

/** Через сколько молчания сохранять правки. */
const SETTLE_MS = 1200;

const MIN_WIDTH = 90;
const MAX_WIDTH = 900;

export function SpecSheet({ card }: { card: Card }) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState<Sheet | null>(null);
  const [trouble, setTrouble] = useState("");
  const [saved, setSaved] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const dirty = useRef(false);

  const { data, isLoading } = useQuery({
    queryKey: ["card", card.id, "sheet"],
    queryFn: () => sheetApi.get(card.id),
    staleTime: 30_000,
  });

  // Сам файл спецификации — из сведений о строке. Ключ тот же, что у ссылки
  // «На площадке» в шапке карточки: ответ уже в кэше вкладки, и второй раз по
  // сети никто не идёт.
  const { data: facts } = useQuery({
    queryKey: [card.module, "item", card.row_id, "facts"],
    queryFn: () =>
      worklists.detail(card.module as WorklistSlug, card.row_id, "", true),
    retry: false,
    staleTime: 60_000,
  });
  const spec = facts?.spec ?? null;

  // Ход разбора живьём. Модель читает три тысячи знаков и раскладывает их по
  // предметам — это минута с лишним, и всё это время кнопка без ответа
  // выглядит как непрожатая: человек жмёт второй раз и платит дважды.
  const run = useJobStream(jobId, () => {
    dirty.current = false;
    void cache.invalidateQueries({ queryKey: ["card", card.id, "sheet"] });
  });
  const building =
    run === null ? jobId !== null : ["queued", "running"].includes(run.status);

  // Пришедшее с сервера становится черновиком только пока человек не правил:
  // иначе фоновое обновление стёрло бы наполовину набранную ячейку.
  useEffect(() => {
    if (data && !dirty.current) setDraft(data);
  }, [data]);

  const save = useMutation({
    mutationFn: (next: Sheet) =>
      sheetApi.save(card.id, { columns: next.columns, rows: next.rows }),
    onSuccess: () => {
      dirty.current = false;
      setSaved(true);
      setTrouble("");
      window.setTimeout(() => setSaved(false), 2000);
    },
    onError: (error) =>
      setTrouble(
        error instanceof ApiError ? error.message : "Не удалось сохранить",
      ),
  });

  const build = useMutation({
    mutationFn: () => sheetApi.build(card.id),
    onSuccess: (started) => {
      setTrouble("");
      setJobId(started.job_id);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  // Отложенное сохранение: правки копятся, запрос уходит через паузу.
  useEffect(() => {
    if (!draft || !dirty.current) return;
    const timer = window.setTimeout(() => save.mutate(draft), SETTLE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  function change(next: Sheet) {
    dirty.current = true;
    setDraft(next);
  }

  if (isLoading || !draft) {
    return (
      <Panel className="px-5 py-6">
        <Spinner label="Читаем разбор…" />
      </Panel>
    );
  }

  const empty = draft.rows.length === 0;

  return (
    <div className="space-y-3">
      <Head
        sheet={draft}
        spec={spec}
        busy={build.isPending || building}
        note={note(run, build.isPending)}
        saving={save.isPending}
        saved={saved}
        onBuild={() => build.mutate()}
      />

      {/* Полоса, пока модель работает. Без неё минута ожидания неотличима от
          зависшей страницы — а именно в этот момент нажимают второй раз. */}
      {building && (
        <div className="rounded-[10px] border border-hairline bg-surface px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <Spinner label={run?.note || "Ставим в очередь…"} />
            <span className="text-xs text-ink-muted tabular-nums">
              {run?.percent ?? 0}%
            </span>
          </div>
          <div className="mt-2.5">
            <Progress percent={run?.percent ?? 0} />
          </div>
        </div>
      )}

      {run?.status === "failed" && (
        <p className="rounded-[10px] border border-critical/40 bg-critical/10 px-4 py-2.5 text-sm text-ink">
          ✕ Разбор не удался. {run.error}
        </p>
      )}

      {draft.trouble && (
        <p className="rounded-[10px] border border-warning/40 bg-warning/5 px-4 py-2.5 text-sm text-ink">
          {draft.trouble}
        </p>
      )}

      {empty ? (
        /* Пустое состояние честно разделяет два случая. «Спецификация ещё не
           разобрана» звучало одинаково и когда файл приложен, и когда его
           вовсе нет, — и по этой фразе нельзя было понять, чего ждать от
           кнопки. */
        <Panel className="px-5 py-8 text-center">
          <p className="text-sm text-ink">
            {spec
              ? `Спецификация приложена: ${spec.name}`
              : "К этой закупке спецификация не приложена."}
          </p>
          <p className="mx-auto mt-1 max-w-lg text-sm text-ink-muted">
            {spec
              ? spec.chars > 0
                ? "Модель разложит требования заказчика по предметам: процессор, память, накопитель. Требования переносятся дословно — по ним потом меряют соответствие заявки."
                : "Файл есть, но текст из него прочитать не удалось — разбор моделью по нему не соберётся. Откройте файл и заполните таблицу руками."
              : "Заполните таблицу руками или проверьте документы на портале: у большинства лотов портала спецификации действительно нет."}
          </p>
          {spec?.url && (
            <p className="mt-2">
              <a
                href={spec.url}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-series-1 hover:underline"
              >
                Скачать {spec.name} ↓
              </a>
            </p>
          )}
          {spec && spec.chars > 0 && (
            <div className="mt-4">
              <Button
                variant="primary"
                onClick={() => build.mutate()}
                disabled={build.isPending || building}
              >
                {note(run, build.isPending) || "Разобрать спецификацию"}
              </Button>
            </div>
          )}
        </Panel>
      ) : (
        <Grid sheet={draft} onChange={change} />
      )}

      {trouble && <p className="text-sm text-critical">{trouble}</p>}
    </div>
  );
}

/**
 * Что на кнопке, пока идёт разбор.
 *
 * Словами о шаге, а не «Подождите»: модель сначала читает спецификацию, потом
 * раскладывает её, и человек по надписи видит, что работа движется. Пустая
 * строка означает «кнопка свободна».
 */
function note(run: JobRun | null, queuing: boolean): string {
  if (queuing) return "Ставим в очередь…";
  if (!run || !["queued", "running"].includes(run.status)) return "";
  return run.note || "Модель разбирает…";
}

/** Полоса над таблицей: чем собрано, когда и чем это пересобрать. */
function Head({
  sheet,
  spec,
  busy,
  note: doing,
  saving,
  saved,
  onBuild,
}: {
  sheet: Sheet;
  /** Файл, из которого разбор собирается. Пусто — площадка его не забрала. */
  spec: SpecFile | null;
  busy: boolean;
  note: string;
  saving: boolean;
  saved: boolean;
  onBuild: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <h2 className="text-sm font-semibold text-ink">Разбор спецификации</h2>
      {/* Сам файл — ссылкой рядом с заголовком. Разбор собирается из него, и
          вопрос «а что там в оригинале» задают ровно здесь: до сих пор файл
          лежал в базе, а из карточки его нельзя было ни увидеть, ни скачать. */}
      <p className="flex-1 text-xs text-ink-muted">
        {spec ? (
          spec.url ? (
            <a
              href={spec.url}
              target="_blank"
              rel="noreferrer"
              title="Скачать файл заказчика с портала"
              className="text-series-1 hover:underline"
            >
              {spec.name} ↓
            </a>
          ) : (
            spec.name
          )
        ) : (
          "первые три столбца заполняет модель, остальные — вы"
        )}
      </p>

      {/* Состояние сохранения словом, а не значком: «сохранено» и «сохраняем»
          на одном месте, и человек не гадает, ушли ли правки. */}
      {saving && <span className="text-xs text-ink-muted">сохраняем…</span>}
      {saved && !saving && (
        <span className="text-xs text-good">✓ сохранено</span>
      )}

      {sheet.rows.length > 0 && (
        <Button variant="ghost" onClick={onBuild} disabled={busy}>
          {doing || "Разобрать заново"}
        </Button>
      )}
    </div>
  );
}

function Grid({
  sheet,
  onChange,
}: {
  sheet: Sheet;
  onChange: (next: Sheet) => void;
}) {
  const total = useMemo(
    () => sheet.columns.reduce((sum, column) => sum + column.width, 0),
    [sheet.columns],
  );

  function setCell(rowKey: string, columnKey: string, value: string) {
    onChange({
      ...sheet,
      rows: sheet.rows.map((row) =>
        row.key === rowKey
          ? { ...row, cells: { ...row.cells, [columnKey]: value } }
          : row,
      ),
    });
  }

  function setColumn(key: string, patch: Partial<SheetColumn>) {
    onChange({
      ...sheet,
      columns: sheet.columns.map((column) =>
        column.key === key ? { ...column, ...patch } : column,
      ),
    });
  }

  function addColumn(after: string) {
    const at = sheet.columns.findIndex((column) => column.key === after);
    const next: SheetColumn = {
      key: freeKey(
        sheet.columns.map((column) => column.key),
        "c",
      ),
      title: "Новый столбец",
      width: 180,
      filled_by: "hand",
    };
    const columns = [...sheet.columns];
    columns.splice(at + 1, 0, next);
    onChange({ ...sheet, columns });
  }

  function dropColumn(key: string) {
    onChange({
      ...sheet,
      columns: sheet.columns.filter((column) => column.key !== key),
      // Значения удалённого столбца тоже уходят: оставленные, они всплыли бы
      // в столбце с тем же ключом, заведённом через месяц под другое.
      rows: sheet.rows.map((row) => {
        const cells = { ...row.cells };
        delete cells[key];
        return { ...row, cells };
      }),
    });
  }

  function addRow() {
    onChange({
      ...sheet,
      rows: [
        ...sheet.rows,
        {
          key: freeKey(
            sheet.rows.map((row) => row.key),
            "r",
          ),
          cells: {},
        },
      ],
    });
  }

  function dropRow(key: string) {
    onChange({ ...sheet, rows: sheet.rows.filter((row) => row.key !== key) });
  }

  return (
    <div className="overflow-x-auto rounded-[10px] border border-hairline">
      <table
        className="w-full border-collapse text-sm"
        style={{ minWidth: total + 90 }}
      >
        <thead>
          <tr className="bg-plane">
            <th className="w-10 border-b border-r border-hairline px-2 py-1.5 text-xs font-normal text-ink-muted">
              №
            </th>
            {sheet.columns.map((column, index) => (
              <Header
                key={column.key}
                column={column}
                last={index === sheet.columns.length - 1}
                canDrop={column.filled_by === "hand"}
                onTitle={(title) => setColumn(column.key, { title })}
                onWidth={(width) => setColumn(column.key, { width })}
                onAdd={() => addColumn(column.key)}
                onDrop={() => dropColumn(column.key)}
              />
            ))}
            <th className="w-10 border-b border-hairline" />
          </tr>
        </thead>

        <tbody>
          {sheet.rows.map((row, index) => (
            <tr key={row.key} className="group align-top hover:bg-plane/40">
              <td className="border-b border-r border-hairline px-2 py-1 text-center text-xs text-ink-muted tabular-nums">
                {index + 1}
              </td>
              {sheet.columns.map((column, at) => (
                <Cell
                  key={column.key}
                  value={row.cells[column.key] ?? ""}
                  width={column.width}
                  last={at === sheet.columns.length - 1}
                  onChange={(value) => setCell(row.key, column.key, value)}
                />
              ))}
              <td className="border-b border-hairline px-1 text-center">
                <button
                  type="button"
                  onClick={() => dropRow(row.key)}
                  title="Убрать строку"
                  className="rounded px-1.5 py-0.5 text-xs text-ink-muted opacity-0 transition group-hover:opacity-100 hover:bg-critical/10 hover:text-critical"
                >
                  ×
                </button>
              </td>
            </tr>
          ))}

          <tr>
            <td
              colSpan={sheet.columns.length + 2}
              className="border-b border-hairline px-2 py-1"
            >
              {/* Строка добавляется снизу: в спецификации нет блока питания,
                  а поставить его надо — дописывают в конец, к остальному. */}
              <button
                type="button"
                onClick={addRow}
                className="rounded px-2 py-1 text-xs text-ink-secondary transition hover:bg-plane hover:text-ink"
              >
                + строка
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/**
 * Заголовок столбца: название правится на месте, край тянется, плюс добавляет
 * соседний.
 *
 * Ширину тянут за правый край — так это устроено в любой таблице, и объяснять
 * не приходится. Пределы стоят от обеих крайностей: ужатый до нуля столбец
 * потом не найти мышью, а растянутый на три экрана прячет соседние.
 */
function Header({
  column,
  last,
  canDrop,
  onTitle,
  onWidth,
  onAdd,
  onDrop,
}: {
  column: SheetColumn;
  last: boolean;
  canDrop: boolean;
  onTitle: (title: string) => void;
  onWidth: (width: number) => void;
  onAdd: () => void;
  onDrop: () => void;
}) {
  const from = useRef<{ x: number; width: number } | null>(null);

  function grab(event: React.PointerEvent<HTMLSpanElement>) {
    event.preventDefault();
    from.current = { x: event.clientX, width: column.width };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function pull(event: React.PointerEvent<HTMLSpanElement>) {
    if (!from.current) return;
    const width = from.current.width + (event.clientX - from.current.x);
    onWidth(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round(width))));
  }

  return (
    <th
      style={{ width: column.width, minWidth: column.width }}
      className={cx(
        "group relative border-b border-hairline px-2 py-1.5 text-left align-bottom",
        !last && "border-r",
      )}
    >
      <span className="flex items-center gap-1">
        <input
          value={column.title}
          onChange={(event) => onTitle(event.target.value)}
          className="min-w-0 flex-1 bg-transparent text-xs font-semibold text-ink outline-none focus:underline"
          aria-label="Название столбца"
        />
        <button
          type="button"
          onClick={onAdd}
          title="Добавить столбец справа"
          className="rounded px-1 text-xs text-ink-muted opacity-0 transition group-hover:opacity-100 hover:bg-surface hover:text-ink"
        >
          +
        </button>
        {canDrop && (
          <button
            type="button"
            onClick={onDrop}
            title="Убрать столбец"
            className="rounded px-1 text-xs text-ink-muted opacity-0 transition group-hover:opacity-100 hover:bg-critical/10 hover:text-critical"
          >
            ×
          </button>
        )}
      </span>

      {/* Полоса шириной в шесть точек: попасть в один пиксель мышью нельзя. */}
      <span
        onPointerDown={grab}
        onPointerMove={pull}
        onPointerUp={() => (from.current = null)}
        title="Потяните, чтобы изменить ширину"
        className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-series-1/40"
      />
    </th>
  );
}

/**
 * Ячейка. Растёт по содержимому, а не прячет его в прокрутку.
 *
 * Требование заказчика — это абзац на пять строк, и вырезанный по высоте
 * ячейки он читается наполовину. Прокрутка внутри ячейки хуже высокой строки:
 * в ней не видно, что текст продолжается.
 */
function Cell({
  value,
  width,
  last,
  onChange,
}: {
  value: string;
  width: number;
  last: boolean;
  onChange: (value: string) => void;
}) {
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [value, width]);

  return (
    <td
      style={{ width, minWidth: width }}
      className={cx("border-b border-hairline p-0", !last && "border-r")}
    >
      <textarea
        ref={box}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={1}
        className="block w-full resize-none bg-transparent px-2 py-1.5 text-sm leading-snug text-ink outline-none focus:bg-surface focus:ring-1 focus:ring-series-1/40"
      />
    </td>
  );
}

/** Свободный ключ: `c1`, `c2`… Порядковый номер занят — берём следующий. */
function freeKey(taken: string[], prefix: string): string {
  const busy = new Set(taken);
  for (let number = 1; ; number += 1) {
    const key = `${prefix}${number}`;
    if (!busy.has(key)) return key;
  }
}
