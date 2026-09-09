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
import { cardsApi, type Attachment, type Card, type Person } from "@/api/cards";
import {
  discussionApi,
  worklists,
  type Message,
  type WorklistSlug,
} from "@/api/worklist";
import { Button, Card as Panel, Spinner, bytes, cx } from "@/ui";
import { BarHead, BarTitle, Chip, stamp } from "./kit";
import { Highlighted, MentionBox, collect } from "./Mentions";

export function Files({ card }: { card: Card }) {
  const cache = useQueryClient();
  const picker = useRef<HTMLInputElement | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["card-files", card.id],
    queryFn: () => cardsApi.files(card.id),
  });

  const add = useMutation({
    mutationFn: (file: File) => cardsApi.attach(card.id, file),
    onSuccess: () =>
      void cache.invalidateQueries({ queryKey: ["card-files", card.id] }),
  });
  const drop = useMutation({
    mutationFn: (linkId: string) => cardsApi.detach(linkId),
    onSuccess: () =>
      void cache.invalidateQueries({ queryKey: ["card-files", card.id] }),
  });

  return (
    <Panel className="overflow-hidden">
      <BarHead>
        <BarTitle>Файлы</BarTitle>
        <span className="ml-auto flex items-center gap-2.5">
          {add.isPending && <Spinner label="Грузим…" />}
          <Button
            variant="secondary"
            disabled={add.isPending}
            onClick={() => picker.current?.click()}
          >
            Приложить
          </Button>
        </span>
      </BarHead>

      <input
        ref={picker}
        type="file"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) add.mutate(file);
          // Сбрасываем выбор: без этого тот же файл вторым нажатием не
          // выбирается — браузер считает, что значение не изменилось.
          event.target.value = "";
        }}
      />

      {add.error && (
        <p className="border-b border-hairline/70 px-[15px] py-2.5 text-[12.5px] text-critical">
          {add.error instanceof Error ? add.error.message : "Не загрузилось"}
        </p>
      )}

      <Portal card={card} />

      {isLoading ? (
        <div className="px-[15px] py-3">
          <Spinner label="Читаем файлы…" />
        </div>
      ) : !data?.length ? (
        <p className="px-[15px] py-[26px] text-center text-[12.5px] text-ink-muted">
          Своих файлов пока нет. Сюда кладут переписку, счета поставщиков и
          снимки экрана — документы заказчика приходят с портала сами.
        </p>
      ) : (
        <ul>
          {data.map((item) => (
            <Row
              key={item.id}
              card={card}
              file={item}
              busy={drop.isPending}
              onDrop={() => drop.mutate(item.id)}
            />
          ))}
        </ul>
      )}
    </Panel>
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
        <p className="truncate text-[13px] font-medium text-ink" title={spec.name}>
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
  busy,
  onDrop,
}: {
  card: Card;
  file: Attachment;
  busy: boolean;
  onDrop: () => void;
}) {
  return (
    <li className="flex items-center gap-[11px] border-b border-hairline/70 px-[15px] py-[11px] last:border-b-0">
      <Kind name={file.name} />
      <div className="min-w-0 flex-1">
        <a
          href={cardsApi.fileUrl(card.id, file.sha256)}
          className="block truncate text-[13px] font-medium text-ink hover:underline"
          title={file.name}
        >
          {file.name}
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
