/**
 * Файлы лота.
 *
 * Документы заказчика и наши — рядом, но раздельно. Раздельно по существу:
 * наши кладут руками и пересборка списка их не трогает, документы заказчика
 * приходят с портала и меняются вместе с закупкой. А искать их человек
 * приходит в одно место — «где спецификация» это вопрос про файл, а не про
 * то, кто его положил.
 *
 * Строкой с квадратом расширения, а не именем в столбик. Имена у файлов
 * портала машинные — `techspec_17569342_43124315.pdf`, — и по такому списку
 * глаз ищет не название, а тип: спецификация это или счёт поставщика.
 *
 * Откуда файл, сказано плашкой, а не порядком строк. Порядок сбивается первым
 * же приложенным вручную документом, а вопрос «это заказчик прислал или мы
 * положили» решает, можно ли на файл ссылаться в замечании.
 *
 * Рядом переписка коллег: обсуждают обычно то, что только что приложили, и
 * половина реплик — это «смотри счёт выше».
 */

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cardsApi,
  type Attachment,
  type Card,
  type Folder,
  type Person,
} from "@/api/cards";
import { ApiError } from "@/api/client";
import {
  discussionApi,
  worklists,
  type Message,
  type WorklistSlug,
} from "@/api/worklist";
import { Button, Card as Panel, Spinner, bytes, cx } from "@/ui";
import { BarHead, BarTitle, Chip, Note, plural, stamp } from "./kit";
import { Highlighted, MentionBox, collect } from "./Mentions";

export function Files({ card }: { card: Card }) {
  const cache = useQueryClient();
  const picker = useRef<HTMLInputElement | null>(null);
  // Куда кладём выбранные файлы. Пусто — в корень. Держится здесь, а не в
  // каждой папке: выбор файлов открывает одно окно на всю вкладку, и по его
  // возврату надо знать, чью кнопку нажимали.
  const [into, setInto] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [trouble, setTrouble] = useState("");
  // Что сервер сказал про последнюю загрузку. Обычно ничего: файл виден в
  // списке, и подпись «загружено» под ним ничего не добавляет. Говорить есть
  // о чём, когда то же содержимое уже лежало в другой папке и переехало.
  const [notices, setNotices] = useState<string[]>([]);
  // Раскрытые папки. Свёрнуты по умолчанию: папку заводят как раз затем, чтобы
  // десяток снимков переписки не тянулся через весь экран, — а развёрнутая по
  // умолчанию она возвращает ровно тот список, от которого уходили. Хранится
  // раскрытое, а не закрытое: закрыто всё, пока не открыли.
  const [openShelves, setOpenShelves] = useState<Record<string, boolean>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["card-files", card.id],
    queryFn: () => cardsApi.files(card.id),
  });
  const { data: folders } = useQuery({
    queryKey: ["card-folders", card.id],
    queryFn: () => cardsApi.folders(card.id),
  });

  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["card-files", card.id] });
    void cache.invalidateQueries({ queryKey: ["card-folders", card.id] });
  };

  const add = useMutation({
    // Пачкой, а не по одному: снимков переписки с поставщиком за день
    // набирается десяток, и десять походов в диалог выбора — это десять
    // поводов положить один не туда.
    mutationFn: async (chosen: { files: File[]; folder: string }) => {
      const said: string[] = [];
      for (const file of chosen.files) {
        const done = await cardsApi.attach(card.id, file, chosen.folder);
        if (done.notice) said.push(done.notice);
      }
      return { said, folder: chosen.folder };
    },
    onSuccess: ({ said, folder }) => {
      setTrouble("");
      setNotices(said);
      // Папка, в которую только что положили, раскрывается сама: человек
      // нажал «+ Файлы» именно у неё и ждёт увидеть, что там оказалось.
      if (folder) setOpenShelves((was) => ({ ...was, [folder]: true }));
      refresh();
    },
    onError: (error) =>
      setTrouble(error instanceof Error ? error.message : "Не загрузилось"),
  });

  const drop = useMutation({
    mutationFn: (linkId: string) => cardsApi.detach(linkId),
    onSuccess: refresh,
  });

  const makeFolder = useMutation({
    mutationFn: () => cardsApi.makeFolder(card.id, name),
    onSuccess: () => {
      setNaming(false);
      setName("");
      setTrouble("");
      refresh();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не завелась"),
  });

  const dropFolder = useMutation({
    mutationFn: (folderId: string) => cardsApi.dropFolder(folderId),
    onSuccess: refresh,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не убралась"),
  });

  const move = useMutation({
    mutationFn: (input: { linkId: string; folder: string }) =>
      cardsApi.moveFile(input.linkId, input.folder),
    onSuccess: refresh,
  });

  const all = data ?? [];
  const shelves = folders ?? [];
  const loose = all.filter((item) => !item.folder_id);
  const twins = numbering(all);

  return (
    <Panel className="overflow-hidden">
      <BarHead>
        <BarTitle>Файлы</BarTitle>
        <Note>папками — чтобы переписка не смешивалась со счетами</Note>
        <span className="ml-auto flex items-center gap-2.5">
          {add.isPending && <Spinner label="Грузим…" />}
          <Button variant="secondary" onClick={() => setNaming((was) => !was)}>
            {naming ? "Не заводить" : "Новая папка"}
          </Button>
          <Button
            variant="secondary"
            disabled={add.isPending}
            onClick={() => {
              setInto("");
              picker.current?.click();
            }}
          >
            Приложить
          </Button>
        </span>
      </BarHead>

      {naming && (
        <div className="flex flex-wrap items-center gap-2 border-b border-hairline/70 bg-plane/40 px-[15px] py-2.5">
          <input
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim()) makeFolder.mutate();
              if (event.key === "Escape") setNaming(false);
            }}
            placeholder="Переписка с поставщиком, Счета, Договоры"
            className={cx(
              "min-w-64 flex-1 rounded-[8px] border border-hairline bg-surface px-2.5 py-1.5",
              "text-[13px] text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <Button
            variant="primary"
            disabled={!name.trim() || makeFolder.isPending}
            onClick={() => makeFolder.mutate()}
          >
            {makeFolder.isPending ? "Заводим…" : "Завести"}
          </Button>
        </div>
      )}

      <input
        ref={picker}
        type="file"
        hidden
        multiple
        onChange={(event) => {
          const chosen = Array.from(event.target.files ?? []);
          if (chosen.length) add.mutate({ files: chosen, folder: into });
          // Сбрасываем выбор: без этого тот же файл вторым нажатием не
          // выбирается — браузер считает, что значение не изменилось.
          event.target.value = "";
        }}
      />

      {trouble && (
        <p className="border-b border-hairline/70 px-[15px] py-2.5 text-[12.5px] text-critical">
          {trouble}
        </p>
      )}

      {/* Не ошибка, а объяснение: файл не пропал, а переехал. Красным это
          красить нельзя — человек ничего не сломал; серым тоже, потому что
          прочитать надо. Закрывается нажатием, само не гаснет: пропавшую
          подсказку человек ищет глазами по всему экрану. */}
      {notices.length > 0 && (
        <div className="flex items-start gap-2.5 border-b border-hairline/70 bg-plane/60 px-[15px] py-2.5">
          <span className="min-w-0 flex-1 space-y-0.5">
            {notices.map((said) => (
              <span
                key={said}
                className="block text-[12.5px] text-ink-secondary"
              >
                {said}
              </span>
            ))}
          </span>
          <button
            type="button"
            onClick={() => setNotices([])}
            className="shrink-0 rounded-[6px] px-1.5 text-[11.5px] text-ink-muted transition hover:bg-plane hover:text-ink"
          >
            Понятно
          </button>
        </div>
      )}

      <Portal card={card} />

      {isLoading ? (
        <div className="px-[15px] py-3">
          <Spinner label="Читаем файлы…" />
        </div>
      ) : (
        <>
          {shelves.map((folder) => (
            <Shelf
              key={folder.id}
              card={card}
              folder={folder}
              folders={shelves}
              files={all.filter((item) => item.folder_id === folder.id)}
              twins={twins}
              open={Boolean(openShelves[folder.id])}
              onToggle={() =>
                setOpenShelves((was) => ({
                  ...was,
                  [folder.id]: !was[folder.id],
                }))
              }
              busy={drop.isPending || move.isPending || dropFolder.isPending}
              onAdd={() => {
                setInto(folder.id);
                picker.current?.click();
              }}
              onDropFolder={() => dropFolder.mutate(folder.id)}
              onDropFile={(linkId) => drop.mutate(linkId)}
              onMove={(linkId, to) => move.mutate({ linkId, folder: to })}
            />
          ))}

          {loose.length > 0 && (
            <ul>
              {loose.map((item) => (
                <Row
                  key={item.id}
                  card={card}
                  file={item}
                  folders={shelves}
                  twin={twins[item.id] ?? 0}
                  busy={drop.isPending || move.isPending}
                  onDrop={() => drop.mutate(item.id)}
                  onMove={(to) => move.mutate({ linkId: item.id, folder: to })}
                />
              ))}
            </ul>
          )}

          {!all.length && !shelves.length && (
            <p className="px-[15px] py-[26px] text-center text-[12.5px] text-ink-muted">
              Своих файлов пока нет. Сюда кладут переписку, счета поставщиков и
              снимки экрана — документы заказчика приходят с портала сами.
              <br />
              Файлов набирается много: заведите папку под каждого поставщика, и
              искать придётся в одной, а не во всех.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}

/**
 * Номера для файлов, названных одинаково.
 *
 * Схлопывание идёт по содержимому, а не по имени: счета от двух поставщиков
 * оба зовутся `invoice.pdf`, и слить их значило бы уйти в заявку с ценой не
 * того. Значит, две строки с одним именем на экране — не сбой, а два разных
 * документа, и человеку нужно чем-то их различать.
 *
 * Номером, а не размером: размер под именем стоит и так, но «160 КБ» и
 * «182 КБ» глаз не запоминает, а «(2)» отвечает на «я точно про этот».
 * Проставляется в порядке приложения, и у одиночных имён его нет вовсе —
 * иначе номер висел бы у каждого второго файла, ничего не различая.
 */
function numbering(files: Attachment[]): Record<string, number> {
  const seen = new Map<string, number>();
  for (const file of files) seen.set(file.name, (seen.get(file.name) ?? 0) + 1);

  const counted = new Map<string, number>();
  const numbers: Record<string, number> = {};
  for (const file of files) {
    if ((seen.get(file.name) ?? 0) < 2) continue;
    const next = (counted.get(file.name) ?? 0) + 1;
    counted.set(file.name, next);
    numbers[file.id] = next;
  }
  return numbers;
}

/**
 * Значок папки.
 *
 * Размером с плашку расширения файла и на её месте — строки папок и строки
 * файлов идут одним списком, и значок, меньший соседнего, ломает левый край:
 * глаз перестаёт видеть столбец и начинает читать каждую строку заново.
 *
 * Жёлтая, потому что папка. Цвет взят из палитры (`series-4`), а не назначен
 * на глаз: он проверен на контраст и на различимость при дальтонизме. Двумя
 * оттенками одного цвета, а не двумя разными — так это читается предметом, а
 * не состоянием: жёлтое рядом с красным «PDF» иначе выглядело бы
 * предупреждением.
 */
function FolderMark({ open }: { open: boolean }) {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center text-series-4"
    >
      <svg viewBox="0 0 32 32" className="h-[26px] w-[26px]">
        {/* Задняя стенка с язычком: по нему папка узнаётся даже в 26 точек. */}
        <path
          fill="currentColor"
          d="M3 8.5A2.5 2.5 0 0 1 5.5 6h6.7c.7 0 1.3.3 1.8.8l2 2c.4.4 1 .7 1.6.7h8.9A2.5 2.5 0 0 1 29 12v11.5a2.5 2.5 0 0 1-2.5 2.5h-21A2.5 2.5 0 0 1 3 23.5z"
        />
        {/* Лист бумаги — белый, чтобы папка не читалась сплошным пятном. */}
        <path
          fill="var(--color-surface)"
          d={open ? "M7 11h18v9H7z" : "M7 11h18v12H7z"}
        />
        {/* Передняя створка. Открытая отклонена — по наклону видно, что
            внутрь заглянули, и это единственный признак, который заметен без
            цвета: рядом стоит ещё и уголок-стрелка. */}
        <path
          fill="currentColor"
          fillOpacity="0.78"
          d={
            open
              ? "M6.2 14h22.3c1 0 1.7 1 1.4 1.9l-2.6 8.8c-.3 1-1.2 1.6-2.2 1.6H3.9c-1 0-1.7-1-1.4-1.9l2.5-8.8c.3-1 1.2-1.6 2.2-1.6z"
              : "M5.5 14h21c.8 0 1.5.7 1.5 1.5v8A2.5 2.5 0 0 1 25.5 26h-19A2.5 2.5 0 0 1 4 23.5v-8c0-.8.7-1.5 1.5-1.5z"
          }
        />
      </svg>
    </span>
  );
}

/**
 * Папка со своими файлами.
 *
 * Свёрнута, пока её не открыли. Папку заводят затем, чтобы десяток снимков
 * переписки с поставщиком не тянулся через весь экран, — развёрнутая по
 * умолчанию, она возвращает ровно тот список, от которого уходили. Со
 * свёрнутыми вкладка помещается в один экран, и видно, что где лежит.
 *
 * Открывается нажатием на всю полосу, а не на уголок: попасть в полосу можно
 * не глядя, а в уголок в двенадцать точек — только прицелившись, и на
 * сенсорном экране мимо него промахиваются через раз.
 *
 * Число файлов написано на самой полосе. Свёрнутая папка иначе не отличается
 * от пустой, и «а туда точно положилось» проверяют открыванием каждой.
 */
function Shelf({
  card,
  folder,
  folders,
  files,
  twins,
  open,
  busy,
  onToggle,
  onAdd,
  onDropFolder,
  onDropFile,
  onMove,
}: {
  card: Card;
  folder: Folder;
  folders: Folder[];
  files: Attachment[];
  /** Номера файлов с одинаковыми именами — по всему лоту, а не по папке. */
  twins: Record<string, number>;
  open: boolean;
  busy: boolean;
  onToggle: () => void;
  onAdd: () => void;
  onDropFolder: () => void;
  onDropFile: (linkId: string) => void;
  onMove: (linkId: string, to: string) => void;
}) {
  const [asking, setAsking] = useState(false);

  return (
    <section className="border-b border-hairline/70 last:border-b-0">
      <div
        className={cx(
          "flex flex-wrap items-center gap-2.5 px-[15px] py-2",
          open ? "bg-plane/60" : "bg-plane/40",
        )}
      >
        {/* Кнопкой, а не строкой с обработчиком: с клавиатуры до неё доходят
            табуляцией, и читалка называет её «свернуть»/«развернуть». */}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-[11px] text-left"
        >
          <FolderMark open={open} />
          <span className="min-w-0">
            <span className="flex items-baseline gap-2">
              <span className="truncate text-[13px] font-semibold text-ink">
                {folder.name}
              </span>
              {/* Уголок — второй признак к наклону створки: цвет и форма в
                  одиночку при дальтонизме не различают открытое от
                  закрытого. */}
              <span
                aria-hidden
                className={cx(
                  "shrink-0 text-[10px] text-ink-muted transition-transform",
                  open && "rotate-90",
                )}
              >
                ▶
              </span>
            </span>
            <Note className="block tabular-nums">
              {files.length
                ? plural(files.length, "файл", "файла", "файлов")
                : "пусто"}
            </Note>
          </span>
        </button>
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={onAdd}
            className="rounded-[6px] px-2 py-0.5 text-[11.5px] font-medium text-series-1 transition hover:underline"
          >
            + Файлы
          </button>
          <button
            type="button"
            onClick={() => setAsking(true)}
            disabled={busy}
            className="rounded-[6px] px-2 py-0.5 text-[11.5px] text-ink-muted transition hover:bg-plane hover:text-ink disabled:opacity-45"
          >
            Убрать папку
          </button>
        </span>
      </div>

      {asking && (
        /* Спрашиваем до, а не сообщаем после: человек должен знать, что
           файлы не пропадут вместе с папкой, — иначе он их сначала
           перенесёт куда-нибудь, а перенос десяти файлов и есть та работа,
           ради ухода от которой папку убирают. */
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline/70 px-[15px] py-2.5">
          <Note>
            {files.length
              ? `${plural(
                  files.length,
                  "файл вернётся в общий список, а не удалится",
                  "файла вернутся в общий список, а не удалятся",
                  "файлов вернутся в общий список, а не удалятся",
                )}.`
              : "Папка пуста."}
          </Note>
          <span className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={() => setAsking(false)}>
              Отмена
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                setAsking(false);
                onDropFolder();
              }}
            >
              Убрать
            </Button>
          </span>
        </div>
      )}

      {open &&
        (files.length === 0 ? (
          <p className="px-[15px] py-3 text-[11.5px] text-ink-muted">
            Пока пусто. «+ Файлы» кладёт сюда — можно сразу пачкой.
          </p>
        ) : (
          <ul>
            {files.map((item) => (
              <Row
                key={item.id}
                card={card}
                file={item}
                folders={folders}
                twin={twins[item.id] ?? 0}
                busy={busy}
                onDrop={() => onDropFile(item.id)}
                onMove={(to) => onMove(item.id, to)}
              />
            ))}
          </ul>
        ))}
    </section>
  );
}

/**
 * Квадрат с расширением вместо значка.
 *
 * Расширение написано словом: значок «документ» одинаков у спецификации и у
 * счёта, а разница между `pdf` и `xlsx` решает, откроется ли файл на планшете
 * снабженца в машине.
 *
 * Цвет — подсказка второго порядка, поэтому три роли и никакой пятой:
 * спецификации приходят в PDF, счета в таблицах, письма в документах.
 */
function Kind({ name }: { name: string }) {
  const tail = (name.split(".").pop() ?? "").toLowerCase();
  const tone = ["pdf"].includes(tail)
    ? "bg-critical/10 text-critical"
    : ["xls", "xlsx", "csv"].includes(tail)
      ? "bg-good/10 text-good"
      : ["doc", "docx", "rtf", "txt"].includes(tail)
        ? "bg-series-1/10 text-series-1"
        : "bg-plane text-ink-muted";

  return (
    <span
      aria-hidden
      className={cx(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px]",
        "text-[9.5px] font-bold tracking-wide uppercase",
        tone,
      )}
    >
      {tail.slice(0, 4) || "файл"}
    </span>
  );
}

/**
 * Документы закупки с портала. Пока это один файл — техническая
 * спецификация, и она же самая нужная: по ней собирают заявку и по ней пишут
 * замечание заказчику.
 *
 * Берётся полем `spec`, а не поиском по разделам разбора. Раньше файл искался
 * перебором полей по ссылке, кончающейся на `/spec`, — и ради этого поиска
 * тянулся полный разбор, который ходит на портал за соседними лотами и
 * отвечает до минуты. Вкладка файлов ждала эту минуту ради одной строки.
 * Теперь тот же запрос сведений, что и у ссылки «На площадке»: ответ уже в
 * кэше вкладки.
 */
function Portal({ card }: { card: Card }) {
  const { data } = useQuery({
    queryKey: [card.module, "item", card.row_id, "facts"],
    queryFn: () =>
      worklists.detail(card.module as WorklistSlug, card.row_id, "", true),
    retry: false,
    staleTime: 60_000,
  });

  const spec = data?.spec;
  if (!spec) return null;

  return (
    <div className="flex items-center gap-[11px] border-b border-hairline/70 px-[15px] py-[11px]">
      <Kind name={spec.name} />
      <div className="min-w-0 flex-1">
        <p
          className="truncate text-[13px] font-medium text-ink"
          title={spec.name}
        >
          {spec.name}
        </p>
        {/* Прочитан файл или нет — разные ответы на «почему разбор пустой».
            Нечитаемый файл выглядел как отсутствующий, и человек шёл жать
            «Разобрать» по второму разу. */}
        <p className="truncate text-[11.5px] text-ink-muted">
          пришёл с портала ·{" "}
          {spec.chars > 0
            ? "по нему собран разбор"
            : "текст прочитать не удалось — разбор моделью не соберётся"}
        </p>
      </div>
      <Chip title="Документ заказчика: приходит выгрузкой и меняется вместе с закупкой">
        с портала
      </Chip>
      {spec.url && (
        <a
          href={spec.url}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-[12.5px] font-medium text-series-1 hover:underline"
        >
          Скачать
        </a>
      )}
    </div>
  );
}

function Row({
  card,
  file,
  folders,
  twin,
  busy,
  onDrop,
  onMove,
}: {
  card: Card;
  file: Attachment;
  /** Куда можно переложить. Пусто — папок у лота ещё нет. */
  folders: Folder[];
  /** Который это файл с таким именем. Ноль — имя у лота одно такое. */
  twin: number;
  busy: boolean;
  onDrop: () => void;
  onMove: (to: string) => void;
}) {
  return (
    <li className="flex items-center gap-[11px] border-b border-hairline/70 px-[15px] py-[11px] last:border-b-0">
      <Kind name={file.name} />
      <div className="min-w-0 flex-1">
        <a
          href={cardsApi.fileUrl(card.id, file.sha256)}
          className="flex items-baseline gap-1.5 text-[13px] font-medium text-ink hover:underline"
          title={file.name}
        >
          <span className="truncate">{file.name}</span>
          {/* Номер стоит вне имени и не подчёркивается вместе с ним: это наша
              пометка, а не часть названия файла — скачается он под своим. */}
          {twin > 0 && (
            <span
              className="shrink-0 text-[11.5px] font-normal text-ink-muted no-underline tabular-nums"
              title="Ещё один файл лота назван так же. Содержимое у них разное — иначе это была бы одна запись"
            >
              ({twin})
            </span>
          )}
        </a>
        <p className="truncate text-[11.5px] text-ink-muted tabular-nums">
          {[
            bytes(file.size_bytes),
            file.added_by && `приложил ${file.added_by}`,
            file.added_at && stamp(file.added_at),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {/* Перекладывание списком, а не перетаскиванием: файл кладут с
          телефона и с ноутбука, а перетаскивание на телефоне не работает
          вовсе. */}
      {folders.length > 0 && (
        <select
          value={file.folder_id}
          disabled={busy}
          onChange={(event) => onMove(event.target.value)}
          aria-label="Папка файла"
          className={cx(
            "shrink-0 rounded-[7px] border border-transparent bg-transparent py-0.5 pr-1 pl-1",
            "text-[11.5px] text-ink-muted transition",
            "hover:border-hairline hover:bg-plane focus:border-series-1 focus:outline-none",
          )}
        >
          <option value="">без папки</option>
          {folders.map((folder) => (
            <option key={folder.id} value={folder.id}>
              {folder.name}
            </option>
          ))}
        </select>
      )}

      <button
        type="button"
        disabled={busy}
        onClick={onDrop}
        title="Убрать с лота. Из хранилища файл не удаляется: тот же файл может быть приложен к соседнему лоту"
        className={cx(
          "shrink-0 rounded-[6px] px-2 py-0.5 text-[11.5px] text-ink-muted transition",
          "hover:bg-plane hover:text-ink disabled:opacity-45",
        )}
      >
        Убрать
      </button>
    </li>
  );
}

/**
 * Переписка коллег по лоту.
 *
 * Не замечание заказчику и не заметка: решение «берём или нет» редко
 * принимает один человек, и мнение снабжения о поставщике должно лежать там
 * же, где цифры разбора, а не в мессенджере.
 */
export function Chat({ card }: { card: Card }) {
  const cache = useQueryClient();
  const [body, setBody] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["card-chat", card.module, card.row_id],
    queryFn: () => discussionApi.thread(card.module, card.row_id),
  });

  // Список сотрудников тот же, что у выбора ответственного: ответ уже в кэше
  // страницы, и второй раз по сети за ним никто не идёт.
  const { data: people } = useQuery({
    queryKey: ["people"],
    queryFn: cardsApi.people,
    staleTime: 10 * 60 * 1000,
  });
  const staff = people ?? [];

  const send = useMutation({
    // Кого позвали, считается по тексту: имя можно набрать руками или
    // вставить из соседней реплики, и человека должно позвать во всех случаях.
    mutationFn: () =>
      discussionApi.write(card.module, card.row_id, body, collect(body, staff)),
    onSuccess: () => {
      setBody("");
      void cache.invalidateQueries({
        queryKey: ["card-chat", card.module, card.row_id],
      });
    },
  });

  const ready = body.trim().length > 0;

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      {isLoading ? (
        <div className="px-5 py-6">
          <Spinner label="Читаем переписку…" />
        </div>
      ) : !data?.length ? (
        <div className="flex flex-1 flex-col items-center justify-center px-5 py-10 text-center">
          <p className="text-sm text-ink">Пока никто ничего не написал.</p>
          <p className="mt-1 max-w-56 text-xs text-ink-muted">
            Мнение снабжения о поставщике нужно там же, где цифры разбора.
          </p>
        </div>
      ) : (
        // Прокручивается сама переписка, а не страница под ней: панель
        // висит поверх, и увести прокрутку наружу значит потерять поле ввода.
        <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-3">
          {data.map((item) => (
            <Reply key={item.id} message={item} people={staff} />
          ))}
        </ul>
      )}

      {/* Поле ввода в своей рамке с полями. Без них оно упиралось в края
          панели: подпись, отступы и края сходились в одну линию, и блок
          выглядел обрезанным по вертикали. */}
      <div className="shrink-0 border-t border-hairline bg-plane/40 px-4 py-3">
        <MentionBox
          value={body}
          people={staff}
          onChange={setBody}
          onSend={() => {
            if (body.trim()) send.mutate();
          }}
          placeholder="Что важно знать по этому лоту. @ — позвать коллегу"
        />
        {/* Подпись и кнопка на своей строке, а не сбоку от поля: рядом с
            полем кнопка сжимала его до половины ширины панели. */}
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-[11px] text-ink-muted">
            Ctrl+Enter — отправить · @all — позвать всех
          </span>
          <Button
            variant="primary"
            disabled={!ready || send.isPending}
            onClick={() => send.mutate()}
          >
            {send.isPending ? "Шлём…" : "Написать"}
          </Button>
        </div>
        {send.isError && (
          <p className="mt-2 text-xs text-critical">
            {send.error instanceof Error
              ? send.error.message
              : "Реплика не ушла"}
          </p>
        )}
      </div>
    </section>
  );
}

function Reply({ message, people }: { message: Message; people: Person[] }) {
  return (
    <li className="rounded-[10px] bg-plane/60 px-3 py-2.5">
      {/* Имя переносится, время — нет: у сотрудников имя с отчеством, и
          сжатое время «0…» рядом с ним не читается вовсе. */}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[13px] font-semibold text-ink">
          {message.author}
        </span>
        <span className="text-[11px] whitespace-nowrap text-ink-muted tabular-nums">
          {new Date(message.created_at).toLocaleString("ru-KZ", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
        {message.edited_at && (
          <span className="text-[11px] text-ink-muted">поправлено</span>
        )}
      </div>
      {/* Позванные подсвечены: реплика, в которой обратились к тебе, должна
          отличаться от той, где просто написали. */}
      <p className="mt-1 text-sm leading-relaxed break-words whitespace-pre-wrap text-ink-secondary">
        <Highlighted body={message.body} people={people} />
      </p>
    </li>
  );
}
