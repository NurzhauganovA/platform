/**
 * Файлы и переписка по лоту.
 *
 * Рядом, а не двумя блоками в разных концах страницы: обсуждают обычно то,
 * что только что приложили, и половина реплик — это «смотри счёт выше».
 *
 * Наши файлы и документы закупки лежат раздельно, но на одном экране.
 * Раздельно по существу: наши кладут руками и пересборка списка их не
 * трогает, документы заказчика приходят с портала и меняются вместе с
 * закупкой. А искать их человек приходит в одно место — «где спецификация»
 * это вопрос про файл, а не про то, кто его положил.
 */

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cardsApi, type Attachment, type Card } from "@/api/cards";
import {
  discussionApi,
  worklists,
  type Message,
  type WorklistSlug,
} from "@/api/worklist";
import { Button, Spinner, bytes, cx } from "@/ui";

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
    <section className="rounded-[10px] border border-hairline bg-surface">
      <header className="flex items-center justify-between gap-4 border-b border-hairline px-4 py-2.5">
        <h2 className="text-sm font-semibold text-ink">Файлы</h2>
        <div className="flex items-center gap-2">
          {add.isPending && <Spinner label="Грузим…" />}
          <Button
            variant="secondary"
            disabled={add.isPending}
            onClick={() => picker.current?.click()}
          >
            Приложить
          </Button>
        </div>
      </header>

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
        <p className="border-b border-hairline px-4 py-2.5 text-sm text-critical">
          {add.error instanceof Error ? add.error.message : "Не загрузилось"}
        </p>
      )}

      <Portal card={card} />

      {isLoading ? (
        <div className="px-4 py-4">
          <Spinner label="Читаем файлы…" />
        </div>
      ) : !data?.length ? (
        <p className="px-4 py-6 text-center text-sm text-ink-muted">
          Ничего не приложено. Сюда кладут переписку, счета поставщиков и снимки
          экрана — документы заказчика приходят с портала сами.
        </p>
      ) : (
        <ul className="divide-y divide-hairline">
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
    </section>
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
    <div className="border-b border-hairline bg-plane/40 px-4 py-2.5">
      <p className="text-xs tracking-wide text-ink-muted uppercase">
        Документы закупки
      </p>
      {spec.url ? (
        <a
          href={spec.url}
          className="mt-1 block truncate text-sm text-ink hover:underline"
          title={spec.name}
        >
          {spec.name}
        </a>
      ) : (
        <p className="mt-1 truncate text-sm text-ink" title={spec.name}>
          {spec.name}
        </p>
      )}
      {/* Прочитан файл или нет — разные ответы на «почему разбор пустой».
          Нечитаемый файл выглядел как отсутствующий, и человек шёл жать
          «Разобрать» по второму разу. */}
      <p className="text-xs text-ink-muted">
        с портала ·{" "}
        {spec.chars > 0
          ? "по нему собирается разбор во вкладке «Разбор»"
          : "текст из него прочитать не удалось — разбор моделью не соберётся"}
      </p>
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
    <li className="flex items-center gap-3 px-4 py-2.5">
      <a
        href={cardsApi.fileUrl(card.id, file.sha256)}
        className="min-w-0 flex-1 truncate text-sm text-ink hover:underline"
        title={file.name}
      >
        {file.name}
      </a>
      <span className="text-xs tabular-nums whitespace-nowrap text-ink-muted">
        {bytes(file.size_bytes)}
      </span>
      {file.added_by && (
        <span className="truncate text-xs text-ink-muted">{file.added_by}</span>
      )}
      <button
        type="button"
        disabled={busy}
        onClick={onDrop}
        title="Убрать с лота. Из хранилища файл не удаляется"
        className="rounded-[6px] px-2 py-0.5 text-xs text-ink-muted transition hover:bg-plane hover:text-ink disabled:opacity-45"
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

  const send = useMutation({
    mutationFn: () => discussionApi.write(card.module, card.row_id, body),
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
            <Reply key={item.id} message={item} />
          ))}
        </ul>
      )}

      {/* Поле ввода в своей рамке с полями. Без них оно упиралось в края
          панели: подпись, отступы и края сходились в одну линию, и блок
          выглядел обрезанным по вертикали. */}
      <div className="shrink-0 border-t border-hairline bg-plane/40 px-4 py-3">
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          onKeyDown={(event) => {
            // Отправка по Ctrl+Enter, а не по Enter: реплики бывают в три
            // строки, и отправленная на первом переносе — это ещё две следом.
            if (
              event.key === "Enter" &&
              (event.metaKey || event.ctrlKey) &&
              body.trim()
            ) {
              send.mutate();
            }
          }}
          rows={3}
          placeholder="Что важно знать по этому лоту"
          className={cx(
            "w-full resize-none rounded-[10px] border border-baseline bg-surface px-3 py-2.5",
            "text-sm leading-relaxed text-ink placeholder:text-ink-muted",
            "focus:border-series-1 focus:outline-none",
          )}
        />
        {/* Подпись и кнопка на своей строке, а не сбоку от поля: рядом с
            полем кнопка сжимала его до половины ширины панели. */}
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-[11px] text-ink-muted">
            Ctrl+Enter - отправить
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

function Reply({ message }: { message: Message }) {
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
      <p className="mt-1 text-sm leading-relaxed break-words whitespace-pre-wrap text-ink-secondary">
        {message.body}
      </p>
    </li>
  );
}
