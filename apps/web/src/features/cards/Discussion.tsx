/**
 * Обсуждение на карточке лота.
 *
 * Замечание к технической спецификации — официальное обращение к заказчику до
 * подачи заявки: мы указываем на требования, сужающие круг участников до
 * одного поставщика, и просим их снять. Снятое требование превращает чужую
 * закупку в нашу, поэтому это не переписка, а инструмент.
 *
 * Раньше за ним уходили в соседний раздел и искали там свой лот. Теперь оно
 * здесь: видно состояние, текст, ответ заказчика, и писать можно не уходя.
 *
 * Не путать с перепиской в чате: та внутренняя, эта — заказчику.
 *
 * **Обсуждение не касается тендерного отбора.** Туда закупки приходят папкой
 * по почте, обсуждать их не с кем — для таких лотов блока нет.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { remarks as api, type Remark, type Stage } from "@/api/remarks";
import { ApiError } from "@/api/client";
import type { Card } from "@/api/cards";
import { Badge, Button, Card as Panel, EmptyState, Spinner, cx } from "@/ui";
import { SpecHint } from "./SpecHint";

/**
 * Переходы обсуждения — те же и в том же порядке, что в разделе обсуждений.
 *
 * Повторены списком, а не взяты оттуда: там они лежат рядом с экраном, у
 * которого своя раскладка, и общий импорт свёл бы две страницы в одну ради
 * пяти строк. Что можно нажать, всё равно решает сервер — `can` в ответе.
 */
const MOVES: { to: Stage; title: string; hint: string; strong?: boolean }[] = [
  { to: "moderation", title: "На проверку", hint: "Передать менеджеру" },
  { to: "drafting", title: "Вернуть на правку", hint: "Ещё дорабатываем" },
  { to: "lawyers", title: "Юристам", hint: "Передать юристам" },
  { to: "not_needed", title: "Не требуется", hint: "Придраться не к чему" },
  {
    to: "sent",
    title: "Отправлено заказчику",
    hint: "Отметить, что замечание ушло. Отменить нельзя",
    strong: true,
  },
];

const WRITING: Record<string, string> = {
  queued: "в очереди на написание",
  running: "модель пишет",
  ready: "написано",
  failed: "написать не удалось",
};

export function Discussion({ card }: { card: Card }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const [trouble, setTrouble] = useState("");

  // Ищем по номеру лота: обсуждение и карточка ключуются одинаково —
  // площадка плюс строка.
  const { data, isLoading } = useQuery({
    // Ключ по площадке, а не по лоту: список один на всю площадку, и два
    // открытых лота должны делить один запрос, а не тянуть его дважды.
    queryKey: ["remarks", { module: card.module }],
    queryFn: () => api.list({ module: card.module }),
    select: (rows: Remark[]) =>
      rows.find((row) => row.row_id === card.row_id) ?? null,
    // Пока модель пишет, текст появляется сам: без этого человек сидит перед
    // пустым полем и не знает, ждать ему или уже нет.
    //
    // Смотрим на сырой ответ, а не на выбранное: `select` до сюда не
    // применяется, и `query.state.data` здесь — весь список.
    refetchInterval: (query) => {
      const found = query.state.data?.find((row) => row.row_id === card.row_id);
      return found?.writing === "running" || found?.writing === "queued"
        ? 5_000
        : false;
    },
  });

  // Черновик сбрасывается, когда пришёл новый текст: иначе правка, начатая до
  // того как домодель дописала, затирает написанное.
  useEffect(() => {
    setDraft(null);
  }, [data?.text]);

  const start = useMutation({
    mutationFn: () => api.start(card.row_id),
    onSuccess: () => {
      setTrouble("");
      void client.invalidateQueries({ queryKey: ["remarks"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const stop = useMutation({
    mutationFn: () => api.stop(card.row_id),
    onSuccess: () => {
      setTrouble("");
      void client.invalidateQueries({ queryKey: ["remarks"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const move = useMutation({
    mutationFn: (to: Stage) => api.move(data?.id ?? "", to),
    onSuccess: () => {
      setTrouble("");
      void client.invalidateQueries({ queryKey: ["remarks"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const save = useMutation({
    mutationFn: (text: string) => api.saveText(data?.id ?? "", text),
    onSuccess: () => {
      setDraft(null);
      setTrouble("");
      void client.invalidateQueries({ queryKey: ["remarks"] });
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не сохранилось"),
  });

  if (card.module === "tender") {
    return (
      <Panel className="px-4 py-8">
        <EmptyState
          title="Здесь обсуждения не ведутся"
          description="Тендерные закупки приходят папкой по почте — обсуждать их не с кем. Там работают детальным разбором."
        />
      </Panel>
    );
  }

  if (isLoading) {
    return (
      <Panel className="px-4 py-6">
        <Spinner label="Читаем обсуждение…" />
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel className="px-4 py-8">
        <EmptyState
          title="Обсуждение не заведено"
          description="Замечание к спецификации пишется до подачи заявки: снятое требование превращает чужую закупку в нашу."
        />
        <div className="mt-4 flex justify-center">
          <Button
            variant="primary"
            onClick={() => start.mutate()}
            disabled={start.isPending}
          >
            {start.isPending ? "Заводим…" : "Завести и написать"}
          </Button>
        </div>
        {trouble && (
          <p className="mt-3 text-center text-sm text-critical">{trouble}</p>
        )}
      </Panel>
    );
  }

  const busy = data.writing === "running" || data.writing === "queued";
  const text = draft ?? data.text;
  const editable = data.can.includes("edit");
  const moves = MOVES.filter((item) => data.can.includes(item.to));

  return (
    <div className="space-y-3">
      <Panel>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
          <Badge tone={data.stage === "sent" ? "good" : "neutral"}>
            {data.stage_name}
          </Badge>
          {data.stage === "sent" && (
            <Badge
              tone={
                data.outcome === "accepted"
                  ? "good"
                  : data.outcome === "rejected"
                    ? "serious"
                    : "neutral"
              }
            >
              {data.outcome_name}
            </Badge>
          )}
          {busy && (
            <span className="flex items-center gap-1.5 text-sm text-ink-secondary">
              <Spinner />
              {WRITING[data.writing]}
              {/* Кнопка рядом с колесом, а не внизу страницы: смотрят в этот
                  момент именно сюда, и искать выход в другом месте экрана
                  человек не станет — он просто уйдёт и вернётся завтра. */}
              <button
                type="button"
                onClick={() => stop.mutate()}
                disabled={stop.isPending}
                title="Снять написание: задача снимается, кнопка отпускается"
                className={cx(
                  "rounded-[6px] px-1.5 py-0.5 text-xs text-ink-muted transition",
                  "hover:bg-critical/10 hover:text-critical",
                  "disabled:cursor-not-allowed disabled:opacity-45",
                )}
              >
                {stop.isPending ? "Останавливаем…" : "Остановить"}
              </button>
            </span>
          )}
          {data.left && (
            <span
              className={cx(
                "text-sm tabular-nums",
                data.burning ? "font-semibold text-critical" : "text-ink-muted",
              )}
            >
              {data.overdue ? "срок прошёл" : `осталось ${data.left}`}
            </span>
          )}
          <Link
            to={`/goszakup/remarks/${data.id}`}
            className="ml-auto text-sm text-series-1 hover:underline"
          >
            Открыть целиком →
          </Link>
        </div>

        {data.trouble && (
          <p className="border-t border-hairline bg-warning/10 px-4 py-2 text-sm text-ink">
            {data.trouble}
          </p>
        )}
      </Panel>

      <Panel title="Текст замечания">
        <div className="space-y-2 px-4 py-3">
          <textarea
            value={text}
            onChange={(event) => setDraft(event.target.value)}
            readOnly={!editable}
            rows={12}
            placeholder={
              busy ? "Модель пишет…" : "Замечание пока пустое — напишите его"
            }
            className={cx(
              "w-full resize-y rounded-[8px] border border-baseline bg-surface px-3 py-2",
              "text-sm leading-relaxed text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
              !editable && "bg-plane",
            )}
          />
          {editable ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                onClick={() => save.mutate(text)}
                disabled={draft === null || save.isPending}
              >
                {save.isPending ? "Сохраняем…" : "Сохранить"}
              </Button>
              {draft !== null && (
                <Button variant="ghost" onClick={() => setDraft(null)}>
                  Вернуть как было
                </Button>
              )}

              {/* Написать заново — только пока текста нет. Модель стоит денег,
                  а перезапуск поверх правленого руками текста затирает работу,
                  которую восстановить неоткуда. Есть текст — сперва очистите
                  поле и сохраните. */}
              {!busy && !data.text.trim() && (
                <Button
                  variant="accent"
                  onClick={() => start.mutate()}
                  disabled={start.isPending}
                  title="Позвать модель ещё раз"
                >
                  {start.isPending ? "Запускаем…" : "Написать моделью"}
                </Button>
              )}
            </div>
          ) : (
            <p className="text-xs text-ink-muted">
              {data.stage === "sent"
                ? "Отправленное не правится: сравнить отправленное с исходным нужно ровно тогда, когда пришёл отказ."
                : "Править замечание вашей роли не открыто."}
            </p>
          )}
          {/* Переходы те же, что в разделе обсуждений, и в том же порядке.
              Раньше отсюда можно было только сохранить текст: передать его
              юристам или отметить отправку человек уходил в соседний раздел и
              искал там свой лот — то самое хождение, ради ухода от которого
              обсуждение и появилось на карточке.

              Что можно нажать, решает сервер: второй набор правил в браузере
              однажды разъедется с первым, и человек нажмёт кнопку, получив
              отказ, — уже будучи уверенным, что отправил. */}
          {moves.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-t border-hairline pt-2.5">
              {moves.map((item) => (
                <Button
                  key={item.to}
                  variant={item.strong ? "primary" : "secondary"}
                  onClick={() => move.mutate(item.to)}
                  disabled={move.isPending || busy}
                  title={item.hint}
                >
                  {item.title}
                </Button>
              ))}
            </div>
          )}

          {trouble && <p className="text-sm text-critical">{trouble}</p>}

          {/* Под полем, а не над: пишут сверху вниз, и требования нужны в тот
              момент, когда рука уже на клавиатуре. Свёрнуто по умолчанию —
              двенадцать предметов системного блока увели бы поле ввода за
              край экрана. */}
          <SpecHint card={card} />
        </div>
      </Panel>

      {data.answer && (
        <Panel title="Ответ заказчика">
          <p className="px-4 py-3 text-sm leading-relaxed text-ink">
            {data.answer}
          </p>
        </Panel>
      )}
    </div>
  );
}
