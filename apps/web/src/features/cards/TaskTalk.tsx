/**
 * Переписка внутри задачи.
 *
 * Отдельно от общей переписки по лоту, и это главное в ней. Общая ветка
 * отвечает на «берём или нет»; у задачи вопрос свой — «что именно найти»,
 * «подойдёт ли вот этот насос», — и в общей он тонет: через неделю не
 * разобрать, о какой из пяти задач по лоту шла речь.
 *
 * Внутри самой задачи, а не кнопкой в углу. Кнопка в углу нужна была там, где
 * переписка идёт поверх чужого экрана; здесь она и есть экран — задачу открыли
 * ради того, чтобы о ней договориться.
 *
 * Своя реплика правится и убирается тут же. В ветке на пять сообщений опечатка
 * в артикуле — это чужой заказ не того товара, и «напишу ещё раз, а то не так
 * понял» удваивает ветку ровно там, где её читают целиком.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cardsApi } from "@/api/cards";
import type { Message } from "@/api/worklist";
import { Button, Spinner, cx } from "@/ui";
import { Highlighted, MentionBox, collect } from "./Mentions";

export function TaskTalk({
  taskId,
  me,
  admin = false,
}: {
  taskId: string;
  /** Кто смотрит: своё правится и убирается, чужое — нет. */
  me: string;
  /** Администратор убирает и чужое: этим правом держится порядок в ветке. */
  admin?: boolean;
}) {
  const cache = useQueryClient();
  const [body, setBody] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["task-talk", taskId],
    queryFn: () => cardsApi.talk(taskId),
    // Обновляется в фоне: ответ приходит, пока человек читает задачу, и
    // узнать о нём он должен без перезагрузки страницы.
    refetchInterval: 30_000,
  });

  // Список сотрудников тот же, что у выбора исполнителя: ответ уже в кэше
  // страницы, и второй раз по сети за ним никто не идёт.
  const { data: people } = useQuery({
    queryKey: ["people"],
    queryFn: cardsApi.people,
    staleTime: 10 * 60 * 1000,
  });
  const staff = people ?? [];

  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["task-talk", taskId] });
    // Число реплик стоит на строке задачи: без обновления списка оно отстаёт
    // ровно на тот разговор, который человек только что и вёл.
    void cache.invalidateQueries({ queryKey: ["errands"] });
    void cache.invalidateQueries({ queryKey: ["desk-tasks"] });
    void cache.invalidateQueries({ queryKey: ["card-tasks"] });
  };

  const send = useMutation({
    // Кого позвали, считается по тексту: имя можно набрать руками или
    // вставить из соседней реплики, и человека должно позвать во всех случаях.
    mutationFn: () => cardsApi.say(taskId, body, collect(body, staff)),
    onSuccess: () => {
      setBody("");
      refresh();
    },
  });

  return (
    <section className="flex min-h-0 flex-col">
      <h4 className="px-3.5 pt-3 text-[11.5px] text-ink-muted">
        Переписка по задаче
      </h4>

      {isLoading ? (
        <div className="px-3.5 py-4">
          <Spinner label="Читаем переписку…" />
        </div>
      ) : !data?.length ? (
        <p className="px-3.5 py-3 text-[12.5px] text-ink-muted">
          Здесь только про эту задачу. Вопрос «какой именно нужен» задают тут, а
          не в общей ветке лота — там он теряется.
        </p>
      ) : (
        <ul className="max-h-72 min-h-0 space-y-1 overflow-y-auto px-3 py-2">
          {data.map((item) => (
            <Reply
              key={item.id}
              taskId={taskId}
              message={item}
              staff={staff}
              own={item.author_id === me || admin}
              onDone={refresh}
            />
          ))}
        </ul>
      )}

      <div className="border-t border-hairline/70 bg-plane/40 px-3.5 py-3">
        <MentionBox
          value={body}
          people={staff}
          rows={2}
          onChange={setBody}
          onSend={() => {
            if (body.trim()) send.mutate();
          }}
          placeholder="Что уточнить по этой задаче. @ — позвать коллегу"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-[11px] text-ink-muted">
            Ctrl+Enter — отправить
          </span>
          <Button
            variant="primary"
            disabled={!body.trim() || send.isPending}
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

function Reply({
  taskId,
  message,
  staff,
  own,
  onDone,
}: {
  taskId: string;
  message: Message;
  staff: { id: string; name: string; role: string }[];
  own: boolean;
  onDone: () => void;
}) {
  // Правка живёт в самой реплике: окно поверх ветки прячет соседние
  // сообщения, а правят обычно как раз по ним — «не тот, что выше».
  const [draft, setDraft] = useState<string | null>(null);

  const fix = useMutation({
    mutationFn: (text: string) =>
      cardsApi.fixSaid(taskId, message.id, text, collect(text, staff)),
    onSuccess: () => {
      setDraft(null);
      onDone();
    },
  });

  const drop = useMutation({
    mutationFn: () => cardsApi.dropSaid(taskId, message.id),
    onSuccess: onDone,
  });

  return (
    <li className="rounded-[10px] bg-plane/60 px-3 py-2.5">
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
        {/* Поправленное помечено: молча изменённый текст в общей ветке — это
            спор о том, кто что сказал. */}
        {message.edited_at && (
          <span className="text-[11px] text-ink-muted">поправлено</span>
        )}
        {own && draft === null && (
          <span className="ml-auto flex gap-1.5">
            <Slight onClick={() => setDraft(message.body)}>поправить</Slight>
            <Slight onClick={() => drop.mutate()}>убрать</Slight>
          </span>
        )}
      </div>

      {draft === null ? (
        <p className="mt-1 text-sm leading-relaxed break-words whitespace-pre-wrap text-ink-secondary">
          <Highlighted body={message.body} people={staff} />
        </p>
      ) : (
        <div className="mt-1.5">
          <MentionBox
            value={draft}
            people={staff}
            rows={2}
            onChange={setDraft}
            onSend={() => draft.trim() && fix.mutate(draft)}
          />
          <div className="mt-1.5 flex gap-2">
            <Button
              variant="primary"
              disabled={!draft.trim() || fix.isPending}
              onClick={() => fix.mutate(draft)}
            >
              Сохранить
            </Button>
            <Button variant="secondary" onClick={() => setDraft(null)}>
              Отмена
            </Button>
          </div>
        </div>
      )}

      {drop.isError && (
        <p className="mt-1 text-[11.5px] text-critical">
          {drop.error instanceof Error ? drop.error.message : "Не убралось"}
        </p>
      )}
    </li>
  );
}

/** Мелкое действие над своей репликой. Словом, а не значком: «карандаш» и
 *  «корзина» в ряду по шесть точек различаются хуже, чем два слова. */
function Slight({
  children,
  onClick,
}: {
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "rounded-[6px] px-1 text-[11px] text-ink-muted transition",
        "hover:bg-surface hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
