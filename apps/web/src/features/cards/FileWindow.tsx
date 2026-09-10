/**
 * Приложенный файл во весь экран.
 *
 * Снимки переписки с поставщиком, счета, договоры на китайском — их смотрят
 * десятками и по одному лоту. Пока «открыть» означало «скачать», каждый такой
 * просмотр был выходом из платформы: файл уезжал в загрузки, открывался чужой
 * программой, и обратно к строке человек возвращался руками.
 *
 * Внутри — тот же просмотрщик, что у документов закупки (`PreviewBody`).
 * Именно тот же, а не похожий: в нём живёт разбор `.docx` и `.xlsx` на абзацы,
 * таблицы и листы, и вторая копия разошлась бы с первой на первой же книге с
 * объединёнными ячейками.
 *
 * Стрелками — соседние файлы папки. Снимки экрана смотрят подряд, и закрывать
 * окно ради следующего значит тридцать закрытий на одну переписку.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { cardsApi, type Attachment } from "@/api/cards";
import { Spinner, bytes, cx } from "@/ui";
import { PreviewBody } from "@/features/worklist/FileViewer";

export function FileWindow({
  cardId,
  file,
  neighbours,
  onMove,
  onClose,
}: {
  cardId: string;
  file: Attachment;
  /** Что лежит рядом — та же папка или общий список. Для стрелок. */
  neighbours: Attachment[];
  onMove: (next: Attachment) => void;
  onClose: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["card-file", cardId, file.sha256],
    queryFn: () => cardsApi.filePreview(cardId, file.sha256),
  });

  const at = neighbours.findIndex((one) => one.id === file.id);
  const before = at > 0 ? neighbours[at - 1] : null;
  const after =
    at >= 0 && at < neighbours.length - 1 ? neighbours[at + 1] : null;

  // Escape закрывает, стрелки листают. Окно во весь экран, и тянуться мышью к
  // крестику после каждого снимка утомительно, а их в папке три десятка.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft" && before) onMove(before);
      if (event.key === "ArrowRight" && after) onMove(after);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, onMove, before, after]);

  // Ссылка на показ и ссылка на скачивание — разные. Показ просит сервер
  // отдать файл во вкладку, скачивание — сохранить его под настоящим именем.
  const shown = cardsApi.fileUrl(cardId, file.sha256, true);
  const saved = cardsApi.fileUrl(cardId, file.sha256);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Файл: ${file.name}`}
      className="fixed inset-0 z-[60] flex flex-col bg-ink/70"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-hairline bg-surface px-5 py-3">
        <div className="min-w-0 flex-1">
          <div
            className="truncate text-sm font-medium text-ink"
            title={file.name}
          >
            {file.name}
          </div>
          <div className="mt-0.5 text-xs text-ink-muted">
            {data ? KINDS[data.kind] : "Открываем…"}
            {file.size_bytes > 0 && ` · ${bytes(file.size_bytes)}`}
            {neighbours.length > 1 && at >= 0 && (
              <span className="tabular-nums">
                {" · "}
                {at + 1} из {neighbours.length}
              </span>
            )}
          </div>
        </div>

        {neighbours.length > 1 && (
          <span className="flex items-center gap-1">
            <Step
              title="Предыдущий (←)"
              disabled={!before}
              onClick={() => before && onMove(before)}
            >
              ←
            </Step>
            <Step
              title="Следующий (→)"
              disabled={!after}
              onClick={() => after && onMove(after)}
            >
              →
            </Step>
          </span>
        )}

        {/* Открыть в соседней вкладке — для тех форматов, где браузер умеет
            больше нашего окна: печать PDF, поиск по странице, увеличение. */}
        <a
          href={shown}
          target="_blank"
          rel="noreferrer"
          className="rounded-[8px] px-2.5 py-1.5 text-sm text-ink-muted transition hover:bg-plane hover:text-ink"
        >
          Во вкладке
        </a>
        <a
          href={saved}
          download={file.name}
          className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
        >
          Скачать
        </a>
        <button
          type="button"
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
            <Spinner label="Открываем файл…" />
          </div>
        ) : isError ? (
          <Trouble
            text={error instanceof Error ? error.message : "Файл не открылся"}
            url={saved}
          />
        ) : data ? (
          <PreviewBody data={data} url={shown} name={file.name} />
        ) : null}
      </div>
    </div>
  );
}

const KINDS: Record<string, string> = {
  pdf: "PDF",
  image: "Изображение",
  document: "Документ Word",
  sheet: "Книга Excel",
  none: "Показать нельзя",
};

function Step({
  children,
  title,
  disabled,
  onClick,
}: {
  children: string;
  title: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "rounded-[8px] px-2.5 py-1.5 text-sm transition",
        disabled
          ? "text-ink-muted/40"
          : "text-ink-muted hover:bg-plane hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/** Не открылось — скачать всё равно можно, и это надо сказать сразу. */
function Trouble({ text, url }: { text: string; url: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="max-w-md text-[13px] text-ink">{text}</p>
      <a
        href={url}
        download
        className="rounded-[8px] border border-baseline bg-surface px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
      >
        Скачать файл
      </a>
    </div>
  );
}
