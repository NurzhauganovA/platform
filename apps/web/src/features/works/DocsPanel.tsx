/**
 * Документы позиции рядом с таблицей, а не вместо неё.
 *
 * Сверять артикул с техническим заданием приходится по каждой позиции, и
 * раньше это означало открыть документ в новой вкладке, прочитать, вернуться,
 * найти строку. На лоте из шести позиций — три десятка переключений, и на
 * каждом теряется место, где остановился.
 *
 * Панель закреплена: страница под ней прокручивается, документ остаётся. Что
 * в ней открыто, помнит сама страница, а не документ, — при переходе на
 * соседнюю позицию панель показывает уже её задание.
 *
 * Снабжению доступна одна вкладка — задание. Исходных бумаг заказчика ему не
 * приходит вовсе: в них цены заключения и печати.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { files, worksApi, type Work, type WorkPosition } from "@/api/worklist";
import { Button, Spinner, cx } from "@/ui";
import { FileViewer, PreviewBody } from "@/features/worklist/FileViewer";

/**
 * Ссылка на документ закупки: «…/item/<строка>/file/<sha256>».
 *
 * Опознаётся по виду адреса — тому же, каким его строит сервер. Разбирать
 * адрес неприятно, но альтернатива это второй список документов в ответе,
 * который однажды разойдётся с первым.
 */
const FILE_LINK = /\/item\/([^/]+)\/file\/([0-9a-f]{64})$/;

type Tab = { key: string; label: string; item: string; sha: string };

export function DocsPanel({
  work,
  position,
  editable,
  onDone,
  onClose,
}: {
  work: Work;
  position: WorkPosition;
  /** Правит задание разбор, и только пока лот у него. */
  editable: boolean;
  onDone: (work: Work) => void;
  onClose: () => void;
}) {
  const tabs: Tab[] = position.documents.flatMap((file) => {
    const address = file.link ? FILE_LINK.exec(file.link) : null;
    if (!address) return [];
    return [
      {
        key: address[2],
        label: file.label || "файл",
        item: decodeURIComponent(address[1]),
        sha: address[2],
      },
    ];
  });

  const [tab, setTab] = useState("spec");
  const [full, setFull] = useState(false);

  // Переключились на другую позицию — панель показывает её задание, а не
  // документ предыдущей: чужое ТЗ под верным заголовком хуже пустой панели.
  useEffect(() => setTab("spec"), [position.id]);

  const opened = tabs.find((item) => item.key === tab);

  return (
    <aside className="sticky top-0 flex h-screen w-[30rem] shrink-0 flex-col border-l border-hairline bg-surface">
      <header className="flex items-start gap-2 border-b border-hairline px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium tabular-nums text-series-1">
            {position.code}
          </div>
          <div
            className="truncate text-sm font-medium text-ink"
            title={position.title}
          >
            {position.title}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Закрыть панель"
          title="Закрыть панель"
          className="rounded-[8px] px-2 py-1 text-sm text-ink-muted transition hover:bg-plane hover:text-ink"
        >
          ✕
        </button>
      </header>

      {tabs.length > 0 && (
        <div className="flex gap-1 overflow-x-auto border-b border-hairline px-3 py-2">
          <Chip active={tab === "spec"} onClick={() => setTab("spec")}>
            Задание
          </Chip>
          {tabs.map((item) => (
            <Chip
              key={item.key}
              active={tab === item.key}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </Chip>
          ))}
        </div>
      )}

      {opened ? (
        <Document
          tab={opened}
          onFull={() => setFull(true)}
          full={full}
          onCloseFull={() => setFull(false)}
        />
      ) : (
        <SpecTab
          work={work}
          position={position}
          editable={editable}
          onDone={onDone}
        />
      )}
    </aside>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "shrink-0 rounded-full px-2.5 py-1 text-xs font-medium transition",
        active
          ? "bg-series-1 text-white"
          : "bg-plane text-ink-secondary hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/** Исходный документ заказчика. Только разбору — снабжению их не приходит. */
function Document({
  tab,
  full,
  onFull,
  onCloseFull,
}: {
  tab: Tab;
  full: boolean;
  onFull: () => void;
  onCloseFull: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["file", "tender", tab.item, tab.sha],
    queryFn: () => files.preview("tender", tab.item, tab.sha),
  });
  const url = files.url("tender", tab.item, tab.sha);

  return (
    <>
      <div className="flex items-center justify-between border-b border-hairline px-4 py-1.5">
        <span className="truncate text-xs text-ink-muted">{data?.name}</span>
        <button
          type="button"
          onClick={onFull}
          className="shrink-0 text-xs text-series-1 transition hover:underline"
        >
          Во весь экран
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto bg-plane text-[12px]">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner label="Открываем…" />
          </div>
        ) : isError || !data ? (
          <p className="px-4 py-3 text-sm text-ink-secondary">
            {error instanceof Error ? error.message : "Документ не открылся"}
          </p>
        ) : (
          <PreviewBody data={data} url={url} name={data.name} />
        )}
      </div>
      {full && (
        <FileViewer
          slug="tender"
          itemId={tab.item}
          sha256={tab.sha}
          name={data?.name ?? ""}
          onClose={onCloseFull}
        />
      )}
    </>
  );
}

/**
 * Техническое задание позиции.
 *
 * Собрано платформой из текста документа заказчика — того же ТЗ, а нет его,
 * то маркетингового заключения. Разбор его не пишет: он читает и, если ядро
 * что-то потеряло, дописывает.
 */
function SpecTab({
  work,
  position,
  editable,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => worksApi.editSpec(work.id, position.id, draft ?? ""),
    onSuccess: (next) => {
      setDraft(null);
      onDone(next);
    },
  });

  useEffect(() => setDraft(null), [position.id]);

  const blank = !position.spec.trim();

  return (
    <>
      <div className="flex items-center justify-between gap-2 border-b border-hairline px-4 py-1.5">
        <span
          className="truncate text-xs text-ink-muted"
          title={position.spec_source}
        >
          {position.spec_source
            ? `собрано из ${position.spec_source}`
            : "собрано из разбора закупки"}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          {!blank && (
            <a
              href={worksApi.specFile(work.id, position.id)}
              className="text-xs text-series-1 transition hover:underline"
              title="Скачать, чтобы переслать поставщику"
            >
              .docx
            </a>
          )}
          {editable && draft === null && (
            <button
              type="button"
              onClick={() => setDraft(position.spec)}
              className="text-xs text-series-1 transition hover:underline"
            >
              {blank ? "Написать" : "Дополнить"}
            </button>
          )}
        </div>
      </div>

      {draft !== null ? (
        <div className="flex min-h-0 flex-1 flex-col px-4 py-3">
          <textarea
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="min-h-0 flex-1 w-full rounded-[8px] border border-baseline bg-surface px-3 py-2 font-mono text-[12px] leading-relaxed text-ink focus:border-series-1 focus:outline-none"
          />
          <p className="mt-1.5 text-xs text-ink-muted">
            Это увидит снабжение вместо документов заказчика. Цен и реквизитов
            здесь быть не должно.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {save.isPending ? "Сохраняем…" : "Сохранить"}
            </Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>
              Отмена
            </Button>
            {save.isError && (
              <span className="text-xs text-critical">
                {save.error instanceof Error
                  ? save.error.message
                  : "Не сохранилось"}
              </span>
            )}
          </div>
        </div>
      ) : blank ? (
        <p className="px-4 py-3 text-sm text-ink-muted">
          Задания нет: в папке закупки не нашлось ни технического задания, ни
          маркетингового заключения. Напишите его — снабжение исходных
          документов не видит.
        </p>
      ) : (
        <pre className="min-h-0 flex-1 overflow-auto px-4 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink-secondary">
          {position.spec}
        </pre>
      )}
    </>
  );
}
