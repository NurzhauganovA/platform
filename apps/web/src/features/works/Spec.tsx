/**
 * Техническое задание позиции — то единственное, что видит снабжение.
 *
 * Исходный документ заказчика ему закрыт: в ТЗ стоят цены ценового заключения,
 * реквизиты сторон и печати, а от цены заказчика считается наша. Поэтому
 * задание собирается платформой заново, из разобранных ядром требований, и
 * правит его разбор — тот, кто документ читал.
 *
 * Правится текстом, а не восемью полями. Задание дописывают: «искать только с
 * сертификатом», «замок З-88 обязателен». Разложенное по полям дописывают так
 * же часто, как заполняют восемь полей, то есть никогда.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { worksApi, type Work, type WorkPosition } from "@/api/worklist";
import { Button, Card, cx } from "@/ui";

export function Spec({
  work,
  position,
  editable,
  onDone,
}: {
  work: Work;
  position: WorkPosition;
  /** Правит только разбор и только пока лот у него. */
  editable: boolean;
  onDone: (work: Work) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [full, setFull] = useState(false);

  const save = useMutation({
    mutationFn: () => worksApi.editSpec(work.id, position.id, draft ?? ""),
    onSuccess: (next) => {
      setDraft(null);
      onDone(next);
    },
  });

  const пусто = !position.spec.trim();

  return (
    <Card className="p-0">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-4 py-2.5">
        <div className="flex items-baseline gap-2">
          <h4 className="text-xs font-semibold tracking-wide text-ink">
            ТЕХНИЧЕСКОЕ ЗАДАНИЕ
          </h4>
          {position.spec_source && (
            <span
              className="truncate text-xs text-ink-muted"
              title={`Собрано из документа: ${position.spec_source}`}
            >
              из {position.spec_source}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!пусто && (
            <a
              href={worksApi.specFile(work.id, position.id)}
              className="rounded-[8px] px-3 py-1.5 text-sm text-ink-secondary transition hover:bg-plane"
              title="Скачать, чтобы переслать поставщику"
            >
              Скачать .docx
            </a>
          )}
          {editable && draft === null && (
            <Button variant="secondary" onClick={() => setDraft(position.spec)}>
              {пусто ? "Написать задание" : "Изменить"}
            </Button>
          )}
        </div>
      </div>

      {draft !== null ? (
        <div className="px-4 py-3">
          <textarea
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={18}
            placeholder="Что нужно купить: наименование, количество, характеристики, требования"
            className={cx(
              "w-full rounded-[8px] border border-baseline bg-surface px-3 py-2",
              "font-mono text-[13px] leading-relaxed text-ink",
              "placeholder:font-sans placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <p className="mt-1.5 text-xs text-ink-muted">
            Это увидит снабжение вместо документов заказчика. Цен и реквизитов
            здесь быть не должно: по ним поставщик поймёт наш потолок.
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
      ) : пусто ? (
        <p className="px-4 py-3 text-sm text-ink-muted">
          {editable
            ? "Задания нет — ядро не нашло требований в документах папки. Напишите его: снабжение исходных документов не видит, и без задания лот не отправить."
            : "Задание не написано. Попросите отдел разбора его заполнить."}
        </p>
      ) : (
        <>
          <pre
            className={cx(
              "overflow-x-auto px-4 py-3 font-mono text-[13px] leading-relaxed",
              "whitespace-pre-wrap text-ink-secondary",
              !full && "max-h-56 overflow-y-hidden",
            )}
          >
            {position.spec}
          </pre>
          {position.spec.length > 700 && (
            <button
              type="button"
              onClick={() => setFull(!full)}
              className="w-full border-t border-hairline py-1.5 text-xs text-series-1 transition hover:bg-plane"
            >
              {full ? "Свернуть" : "Показать задание целиком"}
            </button>
          )}
        </>
      )}
    </Card>
  );
}
