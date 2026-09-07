/**
 * Переписка по лоту — кнопкой в углу, а не вкладкой.
 *
 * Вкладкой она мешала дважды. Во-первых, чтобы написать «смотри спецификацию,
 * там третий пункт», надо было уйти со спецификации — и вернуться, чтобы
 * свериться. Во-вторых, вкладка не показывает, что кто-то написал: человек
 * узнавал о реплике, только зайдя туда, и обычно не заходил.
 *
 * В углу она решает оба: открывается поверх любой вкладки, а число
 * непрочитанного видно всегда.
 *
 * Справа снизу, а не слева: слева меню разделов, и кнопка встала бы поверх
 * него. Нижний правый угол — привычное место для такой кнопки, объяснять его
 * не приходится.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Card } from "@/api/cards";
import { discussionApi } from "@/api/worklist";
import { cx } from "@/ui";
import { Chat } from "./Files";
import { ChatIcon } from "./ChatIcon";

/** Где остановились в прошлый раз — по лоту. */
const SEEN = "fintend:chat-seen";

export function ChatDock({ card }: { card: Card }) {
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => read(card.id));

  const { data } = useQuery({
    queryKey: ["card-chat", card.module, card.row_id],
    queryFn: () => discussionApi.thread(card.module, card.row_id),
    // Обновляется в фоне: реплика приходит, пока человек читает разбор, и
    // узнать о ней он должен без перезагрузки страницы.
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const total = data?.length ?? 0;
  const fresh = Math.max(0, total - seen);

  // Открытое окно считается прочитанным: держать значок над раскрытой
  // перепиской — врать о непрочитанном.
  useEffect(() => {
    if (!open || total === seen) return;
    setSeen(total);
    window.localStorage.setItem(`${SEEN}:${card.id}`, String(total));
  }, [open, total, seen, card.id]);

  // Escape закрывает. Окно поверх страницы, и закрывать его мышью, целясь в
  // крестик, — лишнее движение в разговоре, который ведут на бегу.
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open]);

  return (
    <>
      {open && (
        <section
          className={cx(
            // Ростом окно задаётся здесь, а не внутри переписки: список
            // реплик тянется сам, и без внешней высоты он то в две строки,
            // то во весь экран — окно прыгало на каждую новую реплику.
            "fixed right-5 bottom-20 z-30 flex w-[27rem] flex-col overflow-hidden",
            "h-[34rem] max-h-[calc(100vh-8rem)] max-w-[calc(100vw-2.5rem)]",
            "rounded-[14px] border border-hairline bg-surface shadow-2xl",
          )}
          aria-label="Переписка по лоту"
        >
          {/* Заголовок в две строки. Подпись рядом с названием отжимала
              крестик к краю и переносилась по слову — шапка получалась то в
              одну строку, то в три. */}
          <header className="shrink-0 border-b border-hairline px-4 py-3">
            <div className="flex items-center gap-2">
              <ChatIcon size={18} />
              <h2 className="flex-1 text-sm font-semibold text-ink">
                Переписка
              </h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Свернуть переписку"
                className={cx(
                  "-mr-1 rounded-[8px] px-2 py-0.5 text-ink-muted transition",
                  "hover:bg-plane hover:text-ink",
                )}
              >
                ✕
              </button>
            </div>
            <p className="mt-0.5 text-xs text-ink-muted">
              внутри компании · заказчик её не видит
            </p>
          </header>

          <Chat card={card} />
        </section>
      )}

      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        aria-label={
          fresh > 0 ? `Переписка, ${fresh} новых` : "Переписка по лоту"
        }
        title="Переписка по лоту"
        className={cx(
          "fixed right-5 bottom-5 z-30 flex h-12 items-center gap-2 rounded-full px-4",
          "border border-hairline shadow-lg transition",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-series-1",
          open
            ? "bg-ink text-surface hover:bg-ink/90"
            : "bg-surface text-ink hover:bg-plane",
        )}
      >
        <ChatIcon />
        <span className="text-sm font-medium">Переписка</span>

        {/* Число, а не точка: «есть новое» и «новых семь» — разные поводы
            отвлечься. Цвет подкреплён числом, само по себе оно и читается. */}
        {fresh > 0 && !open && (
          <span className="rounded-full bg-critical px-1.5 py-0.5 text-xs font-semibold text-surface tabular-nums">
            {fresh}
          </span>
        )}
      </button>
    </>
  );
}

/** Сколько реплик человек уже видел в этом лоте. */
function read(cardId: string): number {
  const saved = window.localStorage.getItem(`${SEEN}:${cardId}`);
  const number = Number(saved);
  return Number.isFinite(number) && number > 0 ? number : 0;
}
