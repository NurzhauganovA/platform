/**
 * Задача окном — для тех мест, где рядом нет карточки лота.
 *
 * На столе отдела задачи стояли строками с кнопками «Взять себе» и
 * «Закрыть», а что именно надо сделать, в строке не помещалось: заголовок
 * «Найти товар и подтвердить цены · GZ000082» не говорит ни какой товар, ни к
 * какому сроку, ни что вернуть в ответе. Человек брал задачу вслепую и шёл
 * искать лот, чтобы прочитать её целиком.
 *
 * Внутри — та же карточка задачи, что в правой колонке лота (`TaskCard`).
 * Именно та же, а не похожая: в ней живут правила «закрыть только с отчётом»
 * и «чужую взятую не перехватить», и вторая копия этих правил разошлась бы с
 * первой на первой же правке.
 *
 * Окном, а не панелью: на столе отдела нет ничего, что нужно было бы видеть
 * одновременно с задачей, — а в карточке лота есть, и там задача открывается
 * на месте колонки.
 */

import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Job } from "@/api/cards";
import { cx } from "@/ui";
import { TaskCard } from "./StepRail";

export function TaskWindow({
  task,
  me,
  busy,
  trouble,
  onClose,
  onTake,
  onRelease,
  onFinish,
}: {
  task: Job;
  me: string;
  busy: boolean;
  /** Что ответил сервер, если не получилось. Показывается внутри окна: за
   *  его пределами человек этого не увидит вовсе. */
  trouble?: string;
  onClose: () => void;
  onTake: () => void;
  onRelease: () => void;
  onFinish: (result: string) => void;
}) {
  // Escape закрывает. Окно открывают десятки раз за смену — по одному на
  // задачу, — и тянуться мышью к крестику каждый раз утомительно.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center bg-ink/40 px-4 py-10"
      role="dialog"
      aria-modal="true"
      aria-label="Задача"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="w-full max-w-[520px]">
        <TaskCard
          task={task}
          me={me}
          deskName={task.department_name}
          busy={busy}
          backLabel="Закрыть окно"
          lot={
            <Lot code={task.card_code} title={task.card_title} id={task.card_id} />
          }
          onBack={onClose}
          onTake={onTake}
          onRelease={onRelease}
          onClose={onFinish}
        />
        {trouble && (
          <p
            className={cx(
              "mt-2 rounded-[9px] border border-critical/40 bg-critical/10",
              "px-3 py-2 text-[12.5px] text-ink",
            )}
          >
            {trouble}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Из какого лота задача.
 *
 * Ссылкой: половина задач отдела решается не в задаче, а в лоте — там
 * спецификация, разбор и переписка. Открывается в новой вкладке, чтобы
 * работа со списком задач не терялась вместе с переходом.
 */
function Lot({
  code,
  title,
  id,
}: {
  code: string;
  title: string;
  id: string;
}): ReactNode {
  return (
    <span className="flex flex-wrap items-baseline gap-x-2">
      <Link
        to={`/work/lots/${id}`}
        target="_blank"
        className="font-mono text-[11.5px] text-series-1 hover:underline"
      >
        {code}
      </Link>
      <span className="min-w-0 truncate">{title}</span>
    </span>
  );
}
