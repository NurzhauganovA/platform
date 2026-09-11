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
 * **Отправленное показывается текстом, а не полем ввода.** Обращение уже
 * ушло, править его нельзя, и рамка поля вокруг него обещала обратное:
 * человек правил абзац, жал «Сохранить» и получал отказ. Текст набран в
 * колонку шириной в семьдесят восемь знаков и с воздухом между абзацами —
 * его читают целиком, прежде чем решить, идём ли на подачу.
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
import { Button, Card as Panel, EmptyState, Spinner, cx } from "@/ui";
import { BarHead, BarTitle, Chip, Note, Passed, stamp } from "./kit";
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
      <Panel>
        <EmptyState
          title="Здесь обсуждения не ведутся"
          description="Тендерные закупки приходят папкой по почте — обсуждать их не с кем. Там работают детальным разбором."
        />
      </Panel>
    );
  }

  if (isLoading) {
    return (
      <Panel className="px-[15px] py-[15px]">
        <Spinner label="Читаем обсуждение…" />
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel>
        <EmptyState
          title="Обсуждение не заведено"
          description="Замечание к спецификации пишется до подачи заявки: снятое требование превращает чужую закупку в нашу."
          action={
            <Button
              variant="primary"
              onClick={() => start.mutate()}
              disabled={start.isPending}
            >
              {start.isPending ? "Заводим…" : "Завести и написать"}
            </Button>
          }
        />
        {trouble && (
          <p className="px-[15px] pb-4 text-center text-[12.5px] text-critical">
            {trouble}
          </p>
        )}
      </Panel>
    );
  }

  const busy = data.writing === "running" || data.writing === "queued";
  const text = draft ?? data.text;
  const editable = data.can.includes("edit");
  const moves = MOVES.filter((item) => data.can.includes(item.to));
  const sent = data.stage === "sent";

  return (
    <div className="space-y-2.5">
      <Panel className="overflow-hidden">
        {/* Шапка отвечает на три вопроса разом: где обсуждение, когда это
            случилось и чего ждём. Одной строкой, потому что вопрос один —
            «что с ним сейчас». */}
        <BarHead>
          <Chip tone={sent ? "ok" : "calm"}>{data.stage_name}</Chip>

          {/* Прошедший срок — нулями и цветом, как у приёма заявок. Вопрос к
              нему тот же: успели или нет. Красное значит, что замечание
              заказчику так и не ушло, — а обсуждение затем и заводят, чтобы
              снять требование до подачи; после срока снимать его уже нечем.
              Зелёное с галочкой — ушло, и ответа ждём. */}
          {!sent && data.overdue ? (
            <Passed
              submitted={false}
              missed="Срок обсуждения прошёл, замечание заказчику не отправлено"
              className="text-[11.5px]"
            />
          ) : (
            <Note className="tabular-nums">
              {sent
                ? [data.sent_at && stamp(data.sent_at), whatNext(data)]
                    .filter(Boolean)
                    .join(" · ")
                : data.left
                  ? `осталось ${data.left}`
                  : "срок не назначен"}
            </Note>
          )}

          {busy && (
            <span className="flex items-center gap-1.5 text-[12.5px] text-ink-secondary">
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
                  "rounded-[6px] px-1.5 py-0.5 text-[11.5px] text-ink-muted transition",
                  "hover:bg-critical/10 hover:text-critical",
                  "disabled:cursor-not-allowed disabled:opacity-45",
                )}
              >
                {stop.isPending ? "Останавливаем…" : "Остановить"}
              </button>
            </span>
          )}

          <Link
            to={`/goszakup/remarks/${data.id}`}
            className="ml-auto text-[12.5px] font-medium text-series-1 hover:underline"
          >
            Открыть целиком
          </Link>
        </BarHead>

        {data.trouble && (
          <p className="border-b border-hairline/70 bg-warning/10 px-[15px] py-2 text-[12.5px] text-ink">
            {data.trouble}
          </p>
        )}

        <div className="px-[15px] py-[15px]">
          <BarTitle>Текст замечания</BarTitle>

          {editable ? (
            <>
              <textarea
                value={text}
                onChange={(event) => setDraft(event.target.value)}
                rows={12}
                placeholder={
                  busy
                    ? "Модель пишет…"
                    : "Замечание пока пустое — напишите его"
                }
                className={cx(
                  "mt-2.5 w-full resize-y rounded-[9px] border border-hairline bg-surface px-3 py-2.5",
                  "text-[13.5px] leading-[1.65] text-ink placeholder:text-ink-muted",
                  "focus:border-series-1 focus:outline-none",
                )}
              />
              <div className="mt-2 flex flex-wrap items-center gap-2">
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

                {/* Написать заново — только пока текста нет. Модель стоит
                    денег, а перезапуск поверх правленого руками текста
                    затирает работу, которую восстановить неоткуда. Есть текст
                    — сперва очистите поле и сохраните. */}
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
            </>
          ) : text.trim() ? (
            <>
              <Doc text={text} />
              <Note className="mt-3 block">
                {sent
                  ? "Отправленное не правится. Сравнить с исходным можно, когда придёт отказ."
                  : "Править замечание вашей роли не открыто."}
              </Note>
            </>
          ) : (
            <Note className="mt-2.5 block">
              {busy
                ? "Модель пишет — текст появится сам."
                : "Текста пока нет, а править его вашей роли не открыто."}
            </Note>
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
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-hairline/70 pt-3">
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

          {trouble && (
            <p className="mt-2 text-[12.5px] text-critical">{trouble}</p>
          )}
        </div>

        {/* Под текстом, а не над: пишут сверху вниз, и требования нужны в тот
            момент, когда рука уже на клавиатуре. Свёрнуто по умолчанию —
            двенадцать предметов системного блока увели бы поле ввода за край
            экрана. */}
        <SpecHint card={card} />
      </Panel>

      {data.answer && (
        <Panel className="overflow-hidden">
          <BarHead>
            <BarTitle>Ответ заказчика</BarTitle>
            {data.answered_at && (
              <Note className="tabular-nums">{stamp(data.answered_at)}</Note>
            )}
            <Chip
              tone={
                data.outcome === "accepted"
                  ? "ok"
                  : data.outcome === "rejected"
                    ? "hot"
                    : "calm"
              }
            >
              {data.outcome_name}
            </Chip>
          </BarHead>
          <div className="px-[15px] py-[15px]">
            <Doc text={data.answer} />
          </div>
        </Panel>
      )}
    </div>
  );
}

/**
 * Текст обращения так, как его читают.
 *
 * Колонкой в семьдесят восемь знаков и с чертой слева. Ширина не украшение:
 * строка во весь экран в тысячу шестьсот точек теряется на возврате, и абзац
 * приходится искать глазами заново. Черта отделяет наши слова от подписей
 * вокруг — по ней видно, где кончается интерфейс и начинается документ.
 */
function Doc({ text }: { text: string }) {
  const paragraphs = text
    .split(/\n\s*\n|\n/)
    .map((one) => one.trim())
    .filter(Boolean);

  return (
    <div className="mt-3 border-l-2 border-hairline py-0.5 pl-[15px]">
      {paragraphs.map((one, index) => (
        <p
          key={index}
          className={cx(
            "max-w-[78ch] text-[13.5px] leading-[1.65] text-ink-secondary",
            index > 0 && "mt-[11px]",
          )}
        >
          {one}
        </p>
      ))}
    </div>
  );
}

/** Чего ждём после отправки. Словами, а не одним состоянием: «Отправлено» уже
 *  сказано плашкой слева, а вопрос к отправленному — что дальше. */
function whatNext(data: Remark): string {
  if (data.outcome === "waiting") return "ждём ответа заказчика";
  return data.outcome_name.toLowerCase();
}
