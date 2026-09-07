/**
 * Одно обсуждение.
 *
 * Замечание читает специалист заказчика, и решает он по тексту. Поэтому текст
 * здесь занимает экран, а не делит его с карточками сведений: сведения о
 * закупке идут строкой под заголовком, и этого довольно — что за лот, человек
 * помнит, он его только что открыл.
 *
 * Действия внизу, а не сверху. Порядок работы такой: прочитать, поправить,
 * отправить, — и кнопка отправки, стоящая над непрочитанным текстом, зовёт
 * нажать её раньше времени. Отправка необратима.
 *
 * Кнопки строятся из `can`, который приходит с сервером. Своих правил о том,
 * кому что можно, здесь нет: второй набор однажды разъедется с первым, и
 * человек нажмёт кнопку, получив отказ, — уже будучи уверенным, что отправил.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { remarks as api } from "@/api/remarks";
import type { Outcome, Remark, Stage } from "@/api/remarks";
import { PageHeader } from "@/shell/AppShell";
import { Button, Card, EmptyState, Spinner, cx, money } from "@/ui";
import { Deadline, OutcomeWord, StageWord } from "./marks";

/** Переходы в том порядке, в каком по ним идут. Отправка последняя. */
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

const RESULTS: { key: Outcome; title: string }[] = [
  { key: "accepted", title: "Приняли" },
  { key: "rejected", title: "Отклонили" },
  { key: "complaint", title: "Пишем жалобу" },
  { key: "closed", title: "Закрыть" },
];

export function RemarkPage() {
  const { id = "" } = useParams();
  const cache = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["remark", id],
    queryFn: () => api.one(id),
    // Опрос только пока модель пишет: у готового замечания обновлять нечего,
    // а человек в это время правит текст в поле.
    refetchInterval: (query) =>
      query.state.data?.writing === "running" ||
      query.state.data?.writing === "queued"
        ? 3_000
        : false,
  });

  if (isLoading) {
    return (
      <div className="px-8 py-6">
        <Card className="px-5 py-4">
          <Spinner label="Открываем обсуждение…" />
        </Card>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="px-8 py-6">
        <Card>
          <EmptyState
            title="Обсуждение не открылось"
            description={
              error instanceof Error ? error.message : "Возможно, его убрали"
            }
            action={
              <Link
                to="/goszakup/remarks"
                className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
              >
                Ко всем обсуждениям
              </Link>
            }
          />
        </Card>
      </div>
    );
  }

  const refresh = (fresh: Remark) => {
    cache.setQueryData(["remark", id], fresh);
    void cache.invalidateQueries({ queryKey: ["remarks"] });
  };

  return (
    <>
      <PageHeader
        title={`${data.code} · ${data.title}`}
        subtitle={data.customer}
        action={
          <Link
            to="/goszakup/remarks"
            className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
          >
            ← Ко всем обсуждениям
          </Link>
        }
      />

      <div className="mx-auto max-w-4xl space-y-4 px-8 py-6">
        <Facts remark={data} />
        <Text remark={data} onDone={refresh} />
        {data.stage === "sent" && <Answer remark={data} onDone={refresh} />}
      </div>
    </>
  );
}

/**
 * Сведения одной строкой.
 *
 * Строкой, а не сеткой карточек: их читают мельком и один раз, а место нужно
 * тексту замечания. Срок стоит первым — он единственное, из-за чего эту
 * страницу могут закрыть, не дочитав.
 */
function Facts({ remark }: { remark: Remark }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-sm">
      <span className="flex items-baseline gap-2">
        <span className="text-ink-muted">Осталось</span>
        <Deadline remark={remark} />
      </span>
      <span className="flex items-baseline gap-2">
        <span className="text-ink-muted">Этап</span>
        <StageWord remark={remark} />
        <OutcomeWord remark={remark} />
      </span>
      <span className="flex items-baseline gap-2">
        <span className="text-ink-muted">Лот</span>
        <span className="font-mono text-xs text-ink-secondary">
          {remark.row_id}
        </span>
      </span>
      {remark.amount !== null && (
        <span className="flex items-baseline gap-2">
          <span className="text-ink-muted">Сумма</span>
          <span className="tabular-nums text-ink">
            {money(remark.amount)} ₸
          </span>
        </span>
      )}
      {remark.enstru_code && (
        <span className="flex items-baseline gap-2">
          <span className="text-ink-muted">ЕНС ТРУ</span>
          <span className="font-mono text-xs text-ink-secondary">
            {remark.enstru_code}
          </span>
        </span>
      )}
      {remark.assignee && (
        <span className="flex items-baseline gap-2">
          <span className="text-ink-muted">Ведёт</span>
          <span className="text-ink-secondary">{remark.assignee}</span>
        </span>
      )}
    </div>
  );
}

function Text({
  remark,
  onDone,
}: {
  remark: Remark;
  onDone: (fresh: Remark) => void;
}) {
  const [text, setText] = useState(remark.text);
  const [source, setSource] = useState(false);
  // Правил ли человек это поле. Пока не правил, текст подтягивается с сервера
  // — модель как раз дописывает. После первой правки подмена прекращается:
  // затереть набранное хуже, чем показать устаревшее.
  const touched = useRef(false);
  const field = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!touched.current) setText(remark.text);
  }, [remark.text]);

  // Поле растёт под текст. Замечание перед отправкой читают целиком, и
  // прокрутка внутри коробки на две страницы этому мешает: проверяющий видит
  // четыре абзаца из шести и жмёт «отправлено», решив, что дочитал.
  useEffect(() => {
    const node = field.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.max(node.scrollHeight, 320)}px`;
  }, [text]);

  const save = useMutation({
    mutationFn: () => api.saveText(remark.id, text),
    onSuccess: (fresh) => {
      touched.current = false;
      onDone(fresh);
    },
  });
  const move = useMutation({
    mutationFn: (to: Stage) => api.move(remark.id, to),
    onSuccess: (fresh) => {
      touched.current = false;
      onDone(fresh);
    },
  });

  // Писать руками начали, хотя модель не справилась. Отдельно от «есть
  // текст»: пустое поле, открытое человеком нарочно, и пустое поле, оставшееся
  // после неудачи, выглядят одинаково, а означают разное.
  const [byHand, setByHand] = useState(false);

  const again = useMutation({
    mutationFn: () => api.start(remark.row_id),
    onSuccess: () => onDone({ ...remark, writing: "queued", trouble: "" }),
  });

  const editable = remark.can.includes("edit");
  const changed = text !== remark.text;
  const busy = save.isPending || move.isPending;
  const writing = remark.writing === "running" || remark.writing === "queued";
  const moves = MOVES.filter((item) => remark.can.includes(item.to));
  const failure = save.error ?? move.error;
  const blank = !writing && !remark.text && !text && !byHand;

  return (
    <Card>
      {remark.trouble && <Notice text={remark.trouble} />}

      <div className="px-5 py-4">
        {blank ? (
          <Blank
            remark={remark}
            busy={again.isPending}
            onAgain={() => again.mutate()}
            onByHand={() => setByHand(true)}
          />
        ) : writing ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3">
            <Spinner label="Модель читает спецификацию и пишет замечание" />
            <p className="max-w-sm text-center text-xs text-ink-muted">
              Обычно занимает около минуты. Страницу можно закрыть, работа идёт
              на сервере.
            </p>
          </div>
        ) : (
          <textarea
            ref={field}
            value={text}
            onChange={(event) => {
              touched.current = true;
              setText(event.target.value);
            }}
            readOnly={!editable}
            spellCheck
            placeholder="Текст замечания. Его прочитает специалист заказчика."
            className={cx(
              "w-full resize-none overflow-hidden rounded-[8px] border bg-surface p-4",
              "font-sans text-[15px] leading-[1.7] text-ink",
              "focus:outline-none",
              editable
                ? "border-hairline focus:border-series-1"
                : "border-transparent bg-plane",
            )}
          />
        )}
      </div>

      {!writing && !blank && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-hairline px-5 py-3">
          {editable && (
            <Button
              variant="primary"
              disabled={!changed || busy}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Сохраняем…" : "Сохранить"}
            </Button>
          )}

          {moves.map((item) => (
            <Button
              key={item.to}
              variant={item.strong ? "danger" : "secondary"}
              title={item.hint}
              disabled={busy || changed}
              onClick={() => move.mutate(item.to)}
            >
              {item.title}
            </Button>
          ))}

          {changed && (
            <span className="text-xs text-ink-muted">
              Сначала сохраните правку
            </span>
          )}

          <span className="ml-auto flex items-center gap-3 text-xs text-ink-muted">
            <span className="tabular-nums">{text.length} знаков</span>
            {remark.ai_text && remark.ai_text !== remark.text && (
              <button
                type="button"
                onClick={() => setSource((open) => !open)}
                className="underline decoration-hairline underline-offset-2 hover:text-ink"
              >
                {source ? "скрыть" : "показать"} исходник модели
              </button>
            )}
            {remark.ai_model && <span>{remark.ai_model}</span>}
          </span>
        </footer>
      )}

      {source && remark.ai_text && (
        <div className="border-t border-hairline bg-plane px-5 py-4">
          <p className="mb-2 text-xs text-ink-muted">
            Написано моделью до правки. Нужно, когда пришёл отказ и надо понять,
            чем отправленное отличалось от исходного.
          </p>
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink-secondary">
            {remark.ai_text}
          </pre>
        </div>
      )}

      {failure && (
        <p className="border-t border-hairline px-5 py-3 text-sm text-critical">
          {failure instanceof Error ? failure.message : "Не получилось"}
        </p>
      )}
    </Card>
  );
}

/**
 * Замечания ещё нет.
 *
 * Пустое поле в двадцать строк на месте текста не говорит ничего: непонятно,
 * то ли модель не справилась, то ли её не звали. Здесь написано, что
 * произошло, и предложены оба выхода — позвать снова или написать самому.
 * Второй нужен всегда: модель может не справиться и с третьего раза, а срок
 * идёт.
 */
function Blank({
  remark,
  busy,
  onAgain,
  onByHand,
}: {
  remark: Remark;
  busy: boolean;
  onAgain: () => void;
  onByHand: () => void;
}) {
  const failed = remark.writing === "failed";
  return (
    <div className="flex flex-col items-center gap-4 py-14 text-center">
      <div className="max-w-md space-y-1.5">
        <p className="text-sm font-medium text-ink">
          {failed ? "Замечание не написалось" : "Замечания пока нет"}
        </p>
        <p className="text-sm leading-relaxed text-ink-muted">
          {remark.trouble ||
            "Модель ещё не звали по этой закупке. Она прочитает спецификацию и " +
              "укажет, что в ней ограничивает конкуренцию."}
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Button variant="primary" disabled={busy} onClick={onAgain}>
          {busy
            ? "Ставим в очередь…"
            : failed
              ? "Попробовать снова"
              : "Написать моделью"}
        </Button>
        <Button variant="ghost" onClick={onByHand}>
          Написать самому
        </Button>
      </div>
    </div>
  );
}

/**
 * Полоса с предупреждением над текстом.
 *
 * Над текстом, а не под ним: она говорит, как этот текст читать — например,
 * что спецификацию модель не видела и написала по названию лота.
 */
function Notice({ text }: { text: string }) {
  return (
    <div className="flex gap-3 border-b border-hairline bg-warning/10 px-5 py-3">
      <span
        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warning"
        aria-hidden
      />
      <p className="text-sm leading-relaxed text-ink">{text}</p>
    </div>
  );
}

function Answer({
  remark,
  onDone,
}: {
  remark: Remark;
  onDone: (fresh: Remark) => void;
}) {
  const [answer, setAnswer] = useState(remark.answer);
  const resolve = useMutation({
    mutationFn: (outcome: Outcome) => api.resolve(remark.id, outcome, answer),
    onSuccess: onDone,
  });

  if (!remark.can.includes("resolve")) return null;

  return (
    <Card title="Что ответил заказчик">
      <div className="space-y-3 px-5 py-4">
        <textarea
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          rows={5}
          placeholder="Ответ заказчика как есть. По нему решают, закрывать или писать жалобу."
          className={cx(
            "w-full resize-y rounded-[8px] border border-baseline bg-surface p-3",
            "text-sm leading-relaxed text-ink focus:border-series-1 focus:outline-none",
          )}
        />
        <div className="flex flex-wrap items-center gap-2">
          {RESULTS.map((item) => (
            <Button
              key={item.key}
              variant={remark.outcome === item.key ? "primary" : "secondary"}
              disabled={resolve.isPending}
              onClick={() => resolve.mutate(item.key)}
            >
              {item.title}
            </Button>
          ))}
          {remark.answered_at && (
            <span className="ml-auto text-xs text-ink-muted">
              Ответ записан
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}
