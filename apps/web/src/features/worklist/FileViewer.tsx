/**
 * Документ закупки во весь экран.
 *
 * Раньше в браузере открывался только PDF, а `.docx` и `.xlsx` скачивались:
 * файл уезжал в загрузки, открывался чужой программой, и обратно к строке
 * человек возвращался руками. За смену таких выходов десятки — ТЗ смотрят по
 * каждой закупке.
 *
 * PDF и картинки показываются как есть. Word и Excel сервер разбирает на
 * абзацы, таблицы и листы, а рисует их уже браузер — размётку он не получает
 * и получать не должен: содержимое чужого документа стало бы кодом на нашей
 * странице.
 *
 * Скачать всё равно можно: точная вёрстка, печать и правка — это Word, и
 * подменять его платформа не берётся.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { files, type Preview, type WorklistSlug } from "@/api/worklist";
import { Spinner, bytes, cx } from "@/ui";

export function FileViewer({
  slug,
  itemId,
  sha256,
  name,
  onClose,
}: {
  slug: WorklistSlug;
  itemId: string;
  sha256: string;
  /** Имя из списка документов: показывается, пока разбор идёт. */
  name: string;
  onClose: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["file", slug, itemId, sha256],
    queryFn: () => files.preview(slug, itemId, sha256),
  });

  // Escape закрывает: окно во весь экран, и тянуться мышью к крестику после
  // каждого документа утомительно, а их в папке три десятка.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const url = files.url(slug, itemId, sha256);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Документ: ${name}`}
      className="fixed inset-0 z-[60] flex flex-col bg-ink/70"
    >
      <header className="flex shrink-0 items-center gap-4 border-b border-hairline bg-surface px-6 py-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink" title={name}>
            {data?.name || name}
          </div>
          {data && (
            <div className="mt-0.5 text-xs text-ink-muted">
              {KINDS[data.kind]}
              {data.size_bytes > 0 && ` · ${bytes(data.size_bytes)}`}
            </div>
          )}
        </div>
        <a
          href={url}
          download
          className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
        >
          Скачать
        </a>
        <button
          onClick={onClose}
          aria-label="Закрыть"
          title="Закрыть (Esc)"
          className="rounded-[8px] px-2.5 py-1.5 text-sm text-ink-muted transition hover:bg-plane hover:text-ink"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-auto bg-plane">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner label="Открываем документ…" />
          </div>
        ) : isError ? (
          <Message
            text={
              error instanceof Error ? error.message : "Документ не открылся"
            }
            url={url}
          />
        ) : data ? (
          <Body data={data} url={url} name={name} />
        ) : null}
      </div>
    </div>
  );
}

const KINDS: Record<Preview["kind"], string> = {
  pdf: "PDF",
  image: "Изображение",
  document: "Документ Word",
  sheet: "Книга Excel",
  none: "Показать нельзя",
};

function Body({
  data,
  url,
  name,
}: {
  data: Preview;
  url: string;
  name: string;
}) {
  if (data.kind === "pdf")
    // `iframe`, а не встроенный просмотрщик: у браузера он свой, с поиском и
    // печатью, и написать лучше за вечер нельзя.
    return <iframe src={url} title={name} className="h-full w-full border-0" />;

  if (data.kind === "image")
    return (
      <div className="flex min-h-full items-center justify-center p-6">
        <img
          src={url}
          alt={name}
          className="max-w-full rounded-[8px] bg-surface shadow"
        />
      </div>
    );

  if (data.kind === "none") return <Message text={data.note} url={url} />;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Лист бумаги на сером поле: так документ читается как документ, а не
          как ещё одна таблица платформы. */}
      <article className="rounded-[10px] border border-hairline bg-surface px-8 py-8 shadow-sm">
        {data.kind === "document" ? (
          <Document data={data} />
        ) : (
          <Workbook data={data} />
        )}
      </article>
      {data.truncated && (
        <p className="mt-3 text-center text-xs text-ink-muted">
          Показано начало документа. Целиком — в скачанном файле.
        </p>
      )}
    </div>
  );
}

function Document({ data }: { data: Preview }) {
  if (data.blocks.length === 0)
    return <p className="text-sm text-ink-muted">Документ пуст.</p>;

  return (
    <div className="space-y-3">
      {data.blocks.map((block, index) =>
        block.kind === "table" ? (
          <Grid key={index} rows={block.rows} />
        ) : (
          <p
            key={index}
            className={cx(
              "break-words",
              block.kind === "heading"
                ? "pt-3 text-base font-semibold text-ink"
                : "text-sm leading-relaxed text-ink-secondary",
            )}
          >
            {block.text}
          </p>
        ),
      )}
    </div>
  );
}

function Workbook({ data }: { data: Preview }) {
  if (data.sheets.length === 0)
    return <p className="text-sm text-ink-muted">В книге нет листов.</p>;

  return (
    <div className="space-y-6">
      {data.sheets.map((sheet) => (
        <section key={sheet.title}>
          <h3 className="mb-2 text-sm font-semibold text-ink">{sheet.title}</h3>
          {sheet.rows.length === 0 ? (
            <p className="text-sm text-ink-muted">Лист пуст.</p>
          ) : (
            <Grid rows={sheet.rows} head />
          )}
          {sheet.truncated && (
            <p className="mt-1.5 text-xs text-ink-muted">
              Показаны первые строки листа.
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

/** Таблица документа. Первая строка шапкой — в бумагах так почти всегда. */
function Grid({ rows, head = true }: { rows: string[][]; head?: boolean }) {
  const [first, ...rest] = rows;
  return (
    <div className="overflow-x-auto rounded-[8px] border border-hairline">
      <table className="w-full border-collapse text-[13px]">
        {head && first && (
          <thead>
            <tr className="bg-plane">
              {first.map((cell, index) => (
                <th
                  key={index}
                  className="border-b border-hairline px-3 py-1.5 text-left font-medium text-ink-secondary"
                >
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {(head ? rest : rows).map((row, index) => (
            <tr key={index} className="border-b border-hairline last:border-0">
              {row.map((cell, column) => (
                <td
                  key={column}
                  className="px-3 py-1.5 align-top break-words text-ink"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Message({ text, url }: { text: string; url: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="max-w-md text-sm text-ink-secondary">{text}</p>
      <a
        href={url}
        download
        className="rounded-[8px] border border-baseline bg-surface px-3.5 py-2 text-sm text-ink transition hover:bg-plane"
      >
        Скачать файл
      </a>
    </div>
  );
}
