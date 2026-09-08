/**
 * Разбор технической спецификации таблицей.
 *
 * Заменяет двадцать минут ручной раскладки на лот. Спецификация приходит
 * сплошным текстом, где требования к процессору, памяти и монитору идут подряд
 * через маркеры списка; работать с ней нельзя, пока не разложишь по предметам.
 *
 * Три первых столбца собирает модель, остальные заводят люди — под цену, нашу
 * спецификацию, ссылку на поставщика. Разница видна по самой ячейке: у наших
 * столбцов светлое поле ввода и подсказка внутри, у столбцов модели —
 * обычный текст. Подпись под каждым заголовком повторяла одно и то же пять раз
 * подряд и съедала строку в шапке. Свои столбцы пересборка не трогает.
 *
 * Требование заказчика — самая высокая ячейка: там абзац на казахском и русском
 * подряд. Она держит свою высоту и прокручивается внутри себя. Иначе одна
 * строка спецификации на МФУ растягивает ряд на треть экрана, и таблица из
 * четырёх предметов перестаёт читаться как таблица.
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
import {
  cardsApi,
  sheetApi,
  type Card,
  type Sheet,
  type SheetColumn,
} from "@/api/cards";
import { worklists, type SpecFile, type WorklistSlug } from "@/api/worklist";
import { ApiError } from "@/api/client";
import { jobsApi, useJobStream, type JobRun } from "@/api/jobs";
import { Button, Card as Panel, Progress, Spinner, cx } from "@/ui";
import { BarHead, BarTitle, Note } from "./kit";

/** Через сколько молчания сохранять правки. */
const SETTLE_MS = 1200;

const MIN_WIDTH = 90;
const MAX_WIDTH = 900;

/** Ключи столбцов, которые собирает модель. Те же, что объявляет сервер. */
const DEMAND = "demand";
const BRIEF = "brief";

/**
 * Подсказка в пустой ячейке наших столбцов.
 *
 * Словами работы, а не названием столбца: «Цена» над пустым полем и «Цена»
 * внутри него — это два раза одно и то же, а «— ₸» показывает, чего ждут.
 */
const HINTS: Record<string, string> = {
  price: "— ₸",
  ours: "что предлагаем",
};

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

  // Остановка прогона. Исполнитель смотрит на состояние в базе между шагами,
  // и внутри вызова модели шагов нет — поэтому счёт идёт не на мгновения. Но
  // человеку нужно, чтобы отпустилась кнопка: без неё оборванный прогон
  // держит разбор запертым, и на экране колесо крутится до конца дня.
  const stop = useMutation({
    mutationFn: () => jobsApi.cancel(jobId ?? ""),
    onSuccess: () => setJobId(null),
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не остановилось"),
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
      <Panel className="px-[15px] py-[15px]">
        <Spinner label="Читаем разбор…" />
      </Panel>
    );
  }

  const empty = draft.rows.length === 0;

  function addRow(sheet: Sheet) {
    change({
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

  return (
    <div className="space-y-2.5">
      {/* Полоса, пока модель работает. Без неё минута ожидания неотличима от
          зависшей страницы — а именно в этот момент нажимают второй раз. */}
      {building && (
        <Panel className="px-[15px] py-3">
          <div className="flex items-center justify-between gap-4">
            <Spinner label={run?.note || "Ставим в очередь…"} />
            <span className="flex items-center gap-3">
              <span className="text-[11.5px] text-ink-muted tabular-nums">
                {run?.percent ?? 0}%
              </span>
              <button
                type="button"
                onClick={() => stop.mutate()}
                disabled={!jobId || stop.isPending}
                title="Снять разбор: прогон отменяется, кнопка отпускается"
                className={cx(
                  "rounded-[6px] px-1.5 py-0.5 text-[11.5px] text-ink-muted transition",
                  "hover:bg-critical/10 hover:text-critical",
                  "disabled:cursor-not-allowed disabled:opacity-45",
                )}
              >
                {stop.isPending ? "Останавливаем…" : "Остановить"}
              </button>
            </span>
          </div>
          <div className="mt-2.5">
            <Progress percent={run?.percent ?? 0} />
          </div>
        </Panel>
      )}

      {run?.status === "failed" && (
        <p className="rounded-[10px] border border-critical/40 bg-critical/10 px-[15px] py-2.5 text-[12.5px] text-ink">
          ✕ Разбор не удался. {run.error}
        </p>
      )}

      {draft.trouble && (
        <p className="rounded-[10px] border border-warning/40 bg-warning/10 px-[15px] py-2.5 text-[12.5px] text-ink">
          {draft.trouble}
        </p>
      )}

      {empty ? (
        /* Пустое состояние честно разделяет два случая. «Спецификация ещё не
           разобрана» звучало одинаково и когда файл приложен, и когда его
           вовсе нет, — и по этой фразе нельзя было понять, чего ждать от
           кнопки. */
        <Panel className="px-[15px] py-8 text-center">
          <p className="text-[13px] text-ink">
            {spec
              ? `Спецификация приложена: ${spec.name}`
              : "К этой закупке спецификация не приложена."}
          </p>
          <p className="mx-auto mt-1 max-w-lg text-[12.5px] text-ink-muted">
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
                className="text-[12.5px] font-medium text-series-1 hover:underline"
              >
                Скачать {spec.name} ↓
              </a>
            </p>
          )}
          <div className="mt-4 flex justify-center gap-2">
            {spec && spec.chars > 0 && (
              <Button
                variant="primary"
                onClick={() => build.mutate()}
                disabled={build.isPending || building}
              >
                {note(run, build.isPending) || "Разобрать спецификацию"}
              </Button>
            )}
            <Button variant="secondary" onClick={() => addRow(draft)}>
              Завести строку руками
            </Button>
          </div>
        </Panel>
      ) : (
        <Panel className="overflow-hidden">
          <Head
            sheet={draft}
            spec={spec}
            busy={build.isPending || building}
            note={note(run, build.isPending)}
            saving={save.isPending}
            saved={saved}
            onBuild={() => build.mutate()}
          />

          <Grid sheet={draft} onChange={change} />

          {/* Подвал: добавить строку и передать снабжению. Оба действия — про
              то, что делают после разбора, и стоять им над таблицей незачем. */}
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-t border-hairline/70 px-[15px] py-[11px]">
            <Button variant="secondary" onClick={() => addRow(draft)}>
              + Строка
            </Button>
            <ToSupply card={card} />
          </div>
        </Panel>
      )}

      {trouble && <p className="text-[12.5px] text-critical">{trouble}</p>}
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

/** Полоса над таблицей: чем собрано, сколько заполнено и чем это пересобрать. */
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
  // Заполнено — про наши столбцы, а не про столбцы модели: те приходят
  // заполненными всегда, и считать их значит показывать «4 из 4» над таблицей,
  // в которой не проставлено ни одной цены.
  const own = sheet.columns.filter((column) => column.filled_by === "hand");
  const filled = sheet.rows.filter((row) =>
    own.some((column) => (row.cells[column.key] ?? "").trim() !== ""),
  ).length;

  return (
    <BarHead>
      <BarTitle>Разбор спецификации</BarTitle>

      {/* Сам файл — ссылкой рядом с заголовком. Разбор собирается из него, и
          вопрос «а что там в оригинале» задают ровно здесь: до сих пор файл
          лежал в базе, а из карточки его нельзя было ни увидеть, ни скачать. */}
      {spec ? (
        spec.url ? (
          <a
            href={spec.url}
            target="_blank"
            rel="noreferrer"
            title="Скачать файл заказчика с портала"
            className="min-w-0 truncate text-[12.5px] font-medium text-series-1 hover:underline"
          >
            {spec.name}
          </a>
        ) : (
          <Note className="min-w-0 truncate">{spec.name}</Note>
        )
      ) : (
        <Note>первые три столбца заполняет модель, остальные — вы</Note>
      )}

      <span className="ml-auto flex items-center gap-2.5">
        {/* Состояние сохранения словом, а не значком: «сохранено» и
            «сохраняем» на одном месте, и человек не гадает, ушли ли правки. */}
        {saving && <Note>сохраняем…</Note>}
        {saved && !saving && (
          <span className="text-[11.5px] text-good">✓ сохранено</span>
        )}
        {own.length > 0 && (
          <Note className="tabular-nums">
            заполнено {filled} из {sheet.rows.length}
          </Note>
        )}
        <Button
          variant="secondary"
          onClick={onBuild}
          disabled={busy}
          title="Собрать разбор моделью заново. Ваши столбцы не пострадают"
        >
          {doing || "Разобрать заново"}
        </Button>
      </span>
    </BarHead>
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

  function dropRow(key: string) {
    onChange({ ...sheet, rows: sheet.rows.filter((row) => row.key !== key) });
  }

  return (
    <div className="overflow-x-auto">
      {/* Ширины столбцов задаются раз и держатся: без `table-layout: fixed`
          браузер растягивает столбец по самой длинной ячейке, и требование
          заказчика на пол-абзаца съедает всю строку. */}
      <table
        className="w-full table-fixed border-collapse"
        style={{ minWidth: total + 44 }}
      >
        <thead>
          <tr>
            <th className="w-[34px] border-b border-hairline px-2.5 py-2 text-left text-[11.5px] font-normal text-ink-muted">
              №
            </th>
            {sheet.columns.map((column) => (
              <Header
                key={column.key}
                column={column}
                canDrop={column.filled_by === "hand"}
                onTitle={(title) => setColumn(column.key, { title })}
                onWidth={(width) => setColumn(column.key, { width })}
                onAdd={() => addColumn(column.key)}
                onDrop={() => dropColumn(column.key)}
              />
            ))}
            <th className="w-[26px] border-b border-hairline" />
          </tr>
        </thead>

        <tbody>
          {sheet.rows.map((row, index) => (
            <tr
              key={row.key}
              className="group border-b border-hairline/70 align-top last:border-b-0"
            >
              <td className="px-2.5 py-2.5 text-[11.5px] text-ink-muted tabular-nums">
                {index + 1}
              </td>
              {sheet.columns.map((column) => (
                <Cell
                  key={column.key}
                  column={column}
                  value={row.cells[column.key] ?? ""}
                  onChange={(value) => setCell(row.key, column.key, value)}
                />
              ))}
              <td className="px-1 py-2.5 text-center align-middle">
                <button
                  type="button"
                  onClick={() => dropRow(row.key)}
                  title="Убрать строку"
                  className={cx(
                    "rounded px-1.5 py-0.5 text-[12px] text-ink-muted opacity-0 transition",
                    "group-hover:opacity-100 hover:bg-critical/10 hover:text-critical",
                    "focus-visible:opacity-100",
                  )}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
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
  canDrop,
  onTitle,
  onWidth,
  onAdd,
  onDrop,
}: {
  column: SheetColumn;
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
      className="group relative border-b border-hairline px-2.5 py-2 text-left align-bottom"
    >
      <span className="flex items-center gap-1">
        <input
          value={column.title}
          onChange={(event) => onTitle(event.target.value)}
          className="min-w-0 flex-1 bg-transparent text-[11.5px] font-normal text-ink-muted outline-none focus:text-ink focus:underline"
          aria-label="Название столбца"
        />
        <button
          type="button"
          onClick={onAdd}
          title="Добавить столбец справа"
          className="rounded px-1 text-[11.5px] text-ink-muted opacity-0 transition group-hover:opacity-100 hover:bg-plane hover:text-ink"
        >
          +
        </button>
        {canDrop && (
          <button
            type="button"
            onClick={onDrop}
            title="Убрать столбец"
            className="rounded px-1 text-[11.5px] text-ink-muted opacity-0 transition group-hover:opacity-100 hover:bg-critical/10 hover:text-critical"
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
 * Ячейка. Вид зависит от того, чей столбец.
 *
 * Наши столбцы — светлым полем с подсказкой внутри: по таблице сразу видно,
 * где работа не сделана. Столбцы модели — обычным текстом: рамка вокруг
 * дословного требования заказчика обещает, что его надо править, а править
 * его нельзя, по нему меряют соответствие заявки.
 *
 * Требование держит высоту в сто семьдесят шесть точек и прокручивается само.
 * Растущая по содержимому ячейка на этом столбце давала ряд в треть экрана:
 * спецификация приходит на двух языках подряд.
 */
function Cell({
  column,
  value,
  onChange,
}: {
  column: SheetColumn;
  value: string;
  onChange: (value: string) => void;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const own = column.filled_by === "hand";
  const wordy = column.key === DEMAND;

  // Высота по содержимому, но не выше потолка у требования заказчика: там
  // абзац на казахском и русском подряд, и ряд вырастал на треть экрана.
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [value, column.width]);

  return (
    <td className="px-2.5 py-2.5">
      <textarea
        ref={box}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={1}
        aria-label={column.title}
        placeholder={
          own ? (HINTS[column.key] ?? column.title.toLowerCase()) : ""
        }
        className={cx(
          "block w-full resize-none rounded-[7px] outline-none",
          "placeholder:text-ink-muted",
          own
            ? cx(
                "border border-transparent bg-plane/70 px-[7px] py-[5px]",
                "text-[12.5px] leading-[1.45] text-ink",
                "hover:border-hairline focus:border-series-1",
              )
            : wordy
              ? cx(
                  "max-h-[176px] overflow-y-auto bg-transparent px-1 py-0.5",
                  "text-[11.5px] leading-[1.55] text-ink-secondary",
                  "focus:bg-plane focus:text-ink",
                )
              : cx(
                  "bg-transparent px-1 py-0.5 text-[12.5px] leading-[1.45] text-ink",
                  "focus:bg-plane",
                  column.key === BRIEF && "font-medium",
                ),
        )}
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

/**
 * Передать лот снабжению — в подвале таблицы разбора.
 *
 * Именно здесь: разбор кончается тем, что понятно, какой товар нужен, и
 * следующее действие — найти его и подтвердить цену. Отправлять человека за
 * этим в окно задач, выбирать там отдел и придумывать название значит четыре
 * нажатия вместо одного и четыре разных названия у одной и той же задачи.
 *
 * Задача заводится ничьей и на три часа: столько занимает обзвон поставщиков.
 * Срок ставится здесь, а не берущим, — берущий знает только, свободен ли он
 * сейчас. Назначить конкретного человека отсюда нельзя намеренно: кто свободен,
 * в отделе знают лучше.
 */
function ToSupply({ card }: { card: Card }) {
  const cache = useQueryClient();
  const [trouble, setTrouble] = useState("");
  const [sent, setSent] = useState(false);

  const { data: tasks } = useQuery({
    queryKey: ["card-tasks", card.id, "all"],
    queryFn: () => cardsApi.tasks({ card_id: card.id, state: "all" }),
    staleTime: 15_000,
  });

  // Уже передан — второй раз не предлагаем: две одинаковые задачи в очереди
  // отдела означают, что одну из них кто-то сделает зря.
  const already = (tasks ?? []).some(
    (task) => task.department === "supply" && task.state === "open",
  );

  const ask = useMutation({
    mutationFn: () =>
      cardsApi.addTask(card.id, {
        title: `Найти товар и подтвердить цены · ${card.code}`,
        department: "supply",
        body: "Разбор спецификации собран. Нужны поставщик, цена и срок поставки.",
        due_at: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
      }),
    onSuccess: () => {
      setTrouble("");
      setSent(true);
      void cache.invalidateQueries({ queryKey: ["card-tasks", card.id] });
      void cache.invalidateQueries({ queryKey: ["card-tasks", "open"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  return (
    <span className="ml-auto flex flex-wrap items-center gap-2.5">
      <Note>
        {already
          ? "Задача снабжению уже стоит — она в очереди отдела."
          : sent
            ? "Передано. Снабжение возьмёт задачу и назовёт срок."
            : "Заведём задачу отделу: найти товар, подтвердить цену и срок."}
      </Note>
      {trouble && <span className="text-[12.5px] text-critical">{trouble}</span>}
      <Button
        variant="primary"
        onClick={() => ask.mutate()}
        disabled={already || ask.isPending}
        title="Завести снабжению задачу найти товар. Взять её и назвать срок они смогут сами"
      >
        {ask.isPending ? "Передаём…" : "Передать снабжению"}
      </Button>
    </span>
  );
}
