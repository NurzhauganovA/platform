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
  type SheetKind,
} from "@/api/cards";
import { worklists, type SpecFile, type WorklistSlug } from "@/api/worklist";
import { ApiError } from "@/api/client";
import { jobsApi } from "@/api/jobs";
import { Button, Card as Panel, Spinner, cx } from "@/ui";
import { BarHead, BarTitle, Note } from "./kit";

/** Через сколько молчания сохранять правки. */
const SETTLE_MS = 1200;

const MIN_WIDTH = 90;
const MAX_WIDTH = 900;

/** Ключи столбцов, которые собирает модель. Те же, что объявляет сервер. */
const DEMAND = "demand";
const BRIEF = "brief";

/**
 * Итоги по денежным столбцам.
 *
 * Считаются в браузере, а не на сервере: таблица целиком уже в памяти вкладки,
 * и запрос ради сложения сорока чисел — это полсекунды ожидания на каждое
 * нажатие. Правки при этом сохраняются через паузу, а итог должен меняться
 * вместе с набором, а не после неё.
 *
 * Какие столбцы денежные, решает не заголовок. Названия расходятся — «Цена»,
 * «Цена, ₸», «Закупочная», — и правило по заголовку сломалось бы на первом же
 * переименованном столбце. Признак другой: столбец заводит платформа, и ключ у
 * него известен.
 */
function sums(sheet: Sheet): Record<string, string> {
  const out: Record<string, string> = {};
  for (const column of sheet.columns) {
    if (!MONEY.has(column.key)) continue;
    let sum = 0;
    let seen = 0;
    for (const row of sheet.rows) {
      const value = money(row.cells[column.key] ?? "");
      if (value === null) continue;
      sum += value;
      seen += 1;
    }
    // Пустой столбец итога не получает: «0 ₸» под ценой читается как «мы
    // считаем, что бесплатно», а не как «ещё не заполнено».
    if (seen > 0) out[column.key] = `${sum.toLocaleString("ru-RU")} ₸`;
  }
  return out;
}

/** Столбцы платформы, в которых лежат деньги. */
const MONEY = new Set(["price", "cost"]);

/**
 * Число из ячейки. `null` — там не число.
 *
 * Пишут по-разному: «1 250 000», «1250000», «1 250 000 ₸», «1250,50». Разбор
 * снисходительный намеренно — иначе одна ячейка с хвостом «₸» выкидывает
 * позицию из суммы, и итог тихо расходится с тем, что видно глазами.
 */
function money(raw: string): number | null {
  const clean = raw
    .replace(/\u00a0/g, " ")
    .replace(/[^\d,.-]/g, "")
    .replace(/\s/g, "")
    .replace(",", ".");
  if (!clean || clean === "-" || clean === ".") return null;
  const value = Number(clean);
  return Number.isFinite(value) ? value : null;
}

/**
 * Подсказка в пустой ячейке наших столбцов.
 *
 * Словами работы, а не названием столбца: «Цена» над пустым полем и «Цена»
 * внутри него — это два раза одно и то же, а «— ₸» показывает, чего ждут.
 */
const HINTS: Record<string, string> = {
  price: "— ₸",
  cost: "закупочная, ₸",
  ours: "марка и модель",
};

export function SpecSheet({
  card,
  kind = "analysis",
}: {
  card: Card;
  /**
   * Чья таблица. Разбор и снабжение устроены одинаково и рисуются одним
   * экраном: снабжение продолжает работу разбора теми же строками. Второй
   * такой же экран разошёлся бы с первым на первом же столбце — а расхождение
   * между тем, что считал разборщик, и тем, что видит снабжение, это спор о
   * цене через неделю после подачи.
   */
  kind?: SheetKind;
}) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState<Sheet | null>(null);
  const [trouble, setTrouble] = useState("");
  const [saved, setSaved] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  // Какой вариант открыт. Своим состоянием, а не адресом страницы: варианты
  // сравнивают, переключаясь между ними по нескольку раз, и адрес, меняющийся
  // от каждого нажатия, засоряет историю браузера.
  const [variant, setVariant] = useState("A");
  const dirty = useRef(false);

  const { data, isLoading } = useQuery({
    queryKey: ["card", card.id, "sheet", kind, variant],
    queryFn: () => sheetApi.get(card.id, variant, kind),
    staleTime: 30_000,
    // Пока разбор идёт, таблица перечитывается сама. Опросом, а не потоком
    // событий: поток отвечает на «где именно сейчас модель», а этого никто
    // не спрашивает — спрашивают «уже готово?». Зато поток рвался, и
    // оборванный не отличался от идущего: полоса «Ставим в очередь…» висела
    // на экране после того, как разбор давно закончился. Здесь источник
    // правды один — ответ сервера: есть `job_id`, значит идёт.
    refetchInterval: (query) => (query.state.data?.job_id ? 5_000 : false),
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

  // Идёт ли разбор — по ответу сервера, а не по памяти вкладки. Разбор
  // запускается сам при взятии лота в работу, карточку открывают позже и с
  // другой машины: без серверного признака человек видел бы пустую таблицу,
  // пока модель над ней работает, и нажал бы «Разобрать» второй раз, оплатив
  // ту же спецификацию дважды.
  const running = jobId ?? data?.job_id ?? null;
  const building = Boolean(data?.job_id) || jobId !== null;

  // Пришедшее с сервера становится черновиком только пока человек не правил:
  // иначе фоновое обновление стёрло бы наполовину набранную ячейку.
  useEffect(() => {
    if (data && !dirty.current) setDraft(data);
  }, [data]);

  const save = useMutation({
    // Вариант берётся из самой таблицы, а не из состояния экрана: отложенное
    // сохранение срабатывает через паузу, и за неё человек успевает
    // переключиться — черновик A уехал бы в адрес B и затёр бы его целиком,
    // вместе со скопированными требованиями заказчика.
    mutationFn: (next: Sheet) =>
      sheetApi.save(
        card.id,
        next.variant,
        { columns: next.columns, rows: next.rows },
        next.kind,
      ),
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
    mutationFn: () => jobsApi.cancel(running ?? ""),
    onSuccess: () => {
      setJobId(null);
      // И перечитываем таблицу: пока прогон не снят в базе, сервер продолжает
      // называть его идущим, и кнопка отпустится только после обновления.
      void cache.invalidateQueries({ queryKey: ["card", card.id, "sheet"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не остановилось"),
  });

  const branch = useMutation({
    mutationFn: () => sheetApi.branch(card.id, kind),
    onSuccess: (fresh) => {
      setTrouble("");
      dirty.current = false;
      setVariant(fresh.variant);
      void cache.invalidateQueries({ queryKey: ["card", card.id, "sheet"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не завёлся"),
  });

  const dropVariant = useMutation({
    mutationFn: (letter: string) => sheetApi.drop(card.id, letter, kind),
    onSuccess: (fresh) => {
      setTrouble("");
      dirty.current = false;
      setVariant(fresh.variant);
      void cache.invalidateQueries({ queryKey: ["card", card.id, "sheet"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не убрался"),
  });

  const build = useMutation({
    mutationFn: () => sheetApi.build(card.id, variant),
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
  const supply = kind === "supply";

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
      {/* Полосы прогресса здесь нет намеренно.

          Она показывала проценты и «Ставим в очередь…», а отвечала на вопрос,
          которого никто не задавал: где именно сейчас модель. Спрашивают
          другое — готово или нет. Зато она рвалась: поток событий обрывался,
          оборванный не отличался от идущего, и полоса висела на экране после
          того, как разбор давно закончился, — люди по ней решали, что
          платформа сломалась. Осталась строка в шапке таблицы: она приходит
          от сервера вместе с самой таблицей и гаснет тогда же, когда сервер
          перестаёт называть разбор идущим. */}

      {draft.trouble && (
        <p className="rounded-[10px] border border-warning/40 bg-warning/10 px-[15px] py-2.5 text-[12.5px] text-ink">
          {draft.trouble}
        </p>
      )}

      {(draft.variants.length > 1 || !empty) && (
        <Variants
          letters={draft.variants}
          current={draft.variant}
          can={draft.can}
          busy={branch.isPending || dropVariant.isPending}
          onPick={(letter) => {
            // Черновик сбрасывается вместе с переключением: несохранённая
            // правка варианта A, доехавшая до B, затёрла бы его целиком.
            dirty.current = false;
            setVariant(letter);
          }}
          onBranch={() => branch.mutate()}
          onDrop={(letter) => dropVariant.mutate(letter)}
        />
      )}

      {supply && !draft.handed ? (
        /* Снабжению таблицу заводит разборщик, а не оно само. Пустая таблица
           без объяснения читалась бы как поломка: снабженец видит те же
           столбцы, начинает заполнять — а разборщик в это время правит свою,
           и на согласовании оказываются две разные цены. */
        <Panel className="px-[15px] py-8 text-center">
          <p className="text-[13px] text-ink">
            Разбор ещё не передан снабжению
          </p>
          <p className="mx-auto mt-1 max-w-lg text-[12.5px] text-ink-muted">
            Таблица появится здесь копией разбора — с теми же позициями и
            требованиями заказчика. Дальше она живёт своей жизнью: снабжение
            дописывает поставщика, закупочную цену и срок, а разбор остаётся
            тем, по которому считали участие.
          </p>
          <p className="mx-auto mt-2 max-w-lg text-[12.5px] text-ink-muted">
            Передаёт разборщик кнопкой «Передать снабжению» во вкладке «Разбор».
          </p>
        </Panel>
      ) : empty ? (
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
                {note(building, build.isPending) || "Разобрать спецификацию"}
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
            note={note(building, build.isPending)}
            saving={save.isPending}
            saved={saved}
            onBuild={() => build.mutate()}
            onStop={running ? () => stop.mutate() : undefined}
            stopping={stop.isPending}
          />

          <Grid sheet={draft} onChange={change} />

          {/* Подвал: добавить строку и передать снабжению. Оба действия — про
              то, что делают после разбора, и стоять им над таблицей незачем. */}
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-t border-hairline/70 px-[15px] py-[11px]">
            <Button variant="secondary" onClick={() => addRow(draft)}>
              + Строка
            </Button>
            {!supply && <ToSupply card={card} handed={draft.handed} />}
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
 * Словами о деле, а не «Подождите»: человек должен видеть, что работа
 * началась. Шага при этом не называем — прогресс мы больше не слушаем, а
 * называть шаг, которого не знаешь, значит врать; «Модель разбирает…»
 * верно на всём протяжении.
 */
function note(building: boolean, queuing: boolean): string {
  if (queuing) return "Ставим в очередь…";
  return building ? "Модель разбирает…" : "";
}

/**
 * Варианты разбора: A, B, C…
 *
 * Один и тот же лот собирается по-разному — на своём корпусе и на готовом
 * системном блоке, — и у каждого способа своя цена, свой поставщик и свой
 * срок. Пока вариант был один, второй способ считали в уме или переписывали
 * таблицу поверх первого: сравнить два предложения потом было не с чем.
 *
 * Буквами, а не вкладками с названиями: название варианта («на своём
 * корпусе») живёт в столбце «Наш товар», а сравнивают их по строкам, не по
 * заголовкам. Что можно завести и что удалить, решает сервер — здесь только
 * рисуется.
 */
function Variants({
  letters,
  current,
  can,
  busy,
  onPick,
  onBranch,
  onDrop,
}: {
  letters: string[];
  current: string;
  can: string[];
  busy: boolean;
  onPick: (letter: string) => void;
  onBranch: () => void;
  onDrop: (letter: string) => void;
}) {
  const [asking, setAsking] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-1.5 px-0.5">
      <Note className="mr-1">Вариант</Note>
      {letters.map((letter) => (
        <button
          key={letter}
          type="button"
          onClick={() => onPick(letter)}
          aria-pressed={letter === current}
          className={cx(
            "h-[26px] w-[30px] rounded-[7px] text-[12.5px] font-medium transition",
            letter === current
              ? "bg-ink text-surface"
              : "border border-hairline text-ink-secondary hover:bg-plane",
          )}
        >
          {letter}
        </button>
      ))}

      {can.includes("branch") && (
        <button
          type="button"
          onClick={onBranch}
          disabled={busy}
          title="Завести ещё вариант: требования заказчика те же, наши столбцы пустые"
          className={cx(
            "h-[26px] rounded-[7px] border border-dashed border-baseline px-2.5",
            "text-[12.5px] text-ink-secondary transition hover:bg-plane disabled:opacity-45",
          )}
        >
          + Вариант
        </button>
      )}

      {can.includes("drop") &&
        (asking ? (
          <span className="ml-auto flex items-center gap-2">
            <Note>Вариант «{current}» и всё, что в нём набрано?</Note>
            <Button variant="ghost" onClick={() => setAsking(false)}>
              Отмена
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                setAsking(false);
                onDrop(current);
              }}
            >
              Удалить
            </Button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className={cx(
              "ml-auto rounded-[6px] px-2 py-0.5 text-[11.5px] text-ink-muted transition",
              "hover:bg-plane hover:text-ink",
            )}
          >
            Удалить вариант «{current}»
          </button>
        ))}
    </div>
  );
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
  onStop,
  stopping,
}: {
  sheet: Sheet;
  /** Файл, из которого разбор собирается. Пусто — площадка его не забрала. */
  spec: SpecFile | null;
  busy: boolean;
  note: string;
  saving: boolean;
  saved: boolean;
  onBuild: () => void;
  /** Снять идущий разбор. Пусто — снимать нечего. */
  onStop?: () => void;
  stopping?: boolean;
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
        {/* Идущий разбор — строкой здесь, а не полосой над таблицей. Полоса
            занимала блок и висела после окончания работы; строка приходит с
            той же таблицей и гаснет вместе с признаком сервера. */}
        {doing && (
          <span className="flex items-center gap-2">
            <Spinner label={doing} />
            {onStop && (
              <button
                type="button"
                onClick={onStop}
                disabled={stopping}
                title="Снять разбор: прогон отменяется, кнопка отпускается"
                className={cx(
                  "rounded-[6px] px-1.5 py-0.5 text-[11.5px] text-ink-muted transition",
                  "hover:bg-critical/10 hover:text-critical",
                  "disabled:cursor-not-allowed disabled:opacity-45",
                )}
              >
                {stopping ? "Останавливаем…" : "Остановить"}
              </button>
            )}
          </span>
        )}

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
          Разобрать заново
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
  const totals = useMemo(() => sums(sheet), [sheet]);

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
                // Убрать можно любой столбец, включая модельные: в варианте
                // «B» требование заказчика бывает лишним — там сравнивают
                // наши предложения, а не переписывают спецификацию. Пересборка
                // моделью вернёт свои три столбца обратно, и об этом сказано в
                // подсказке.
                canDrop
                total={totals[column.key]}
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
                    // Виден всегда, но приглушённо. Пока крестик появлялся
                    // только под мышью, о нём не знали: строку, добавленную по
                    // ошибке, оставляли в таблице и писали в ней «не надо».
                    "rounded px-1.5 py-0.5 text-[12px] text-ink-muted opacity-40 transition",
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
  total,
  onTitle,
  onWidth,
  onAdd,
  onDrop,
}: {
  column: SheetColumn;
  canDrop: boolean;
  /** Итог по столбцу. Пусто — столбец не денежный или в нём нет чисел. */
  total?: string;
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
          className="rounded px-1 text-[11.5px] text-ink-muted opacity-40 transition group-hover:opacity-100 hover:bg-plane hover:text-ink"
        >
          +
        </button>
        {canDrop && (
          <button
            type="button"
            onClick={onDrop}
            title={
              column.filled_by === "model"
                ? "Убрать столбец. Разбор заново вернёт его обратно"
                : "Убрать столбец"
            }
            className="rounded px-1 text-[11.5px] text-ink-muted opacity-40 transition group-hover:opacity-100 hover:bg-critical/10 hover:text-critical"
          >
            ×
          </button>
        )}
      </span>

      {/* Итог под заголовком, а не строкой в подвале таблицы. Строк в разборе
          бывает под сорок, и подвал уезжает за нижний край экрана: сумму
          спрашивают на планёрке вслух, а искать её прокруткой — это те самые
          пять секунд молчания. Складываются только денежные столбцы: в
          «Кратко» числа тоже есть, но сумма ядер и гигабайтов не значит
          ничего. */}
      {total && (
        <span
          className="mt-0.5 block truncate text-[12px] font-semibold text-ink tabular-nums"
          title={`Итого по столбцу «${column.title}»`}
        >
          {total}
        </span>
      )}

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
function ToSupply({ card, handed }: { card: Card; handed: boolean }) {
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
    // Два действия одним нажатием, и они неразделимы. Задача без таблицы
    // означает снабженца, который открыл пустую вкладку и пошёл спрашивать;
    // таблица без задачи — таблицу, о которой никто не знает. Раньше кнопка
    // делала только первое, и вкладки «Снабжение» не было вовсе.
    mutationFn: async () => {
      await sheetApi.handover(card.id);
      return cardsApi.addTask(card.id, {
        title: `Найти товар и подтвердить цены · ${card.code}`,
        department: "supply",
        body: "Разбор спецификации собран и передан таблицей во вкладку «Снабжение». Нужны поставщик, цена и срок поставки.",
        due_at: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
      });
    },
    onSuccess: () => {
      setTrouble("");
      setSent(true);
      void cache.invalidateQueries({ queryKey: ["card-tasks", card.id] });
      void cache.invalidateQueries({ queryKey: ["card-tasks", "open"] });
      void cache.invalidateQueries({ queryKey: ["card", card.id, "sheet"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  return (
    <span className="ml-auto flex flex-wrap items-center gap-2.5">
      <Note>
        {already || handed
          ? "Передано: таблица во вкладке «Снабжение», задача в очереди отдела."
          : sent
            ? "Передано. Снабжение возьмёт задачу и назовёт срок."
            : "Скопируем таблицу во вкладку «Снабжение» и заведём задачу отделу."}
      </Note>
      {trouble && (
        <span className="text-[12.5px] text-critical">{trouble}</span>
      )}
      <Button
        variant="primary"
        onClick={() => ask.mutate()}
        disabled={already || handed || ask.isPending}
        title="Завести снабжению задачу найти товар. Взять её и назвать срок они смогут сами"
      >
        {ask.isPending ? "Передаём…" : "Передать снабжению"}
      </Button>
    </span>
  );
}
