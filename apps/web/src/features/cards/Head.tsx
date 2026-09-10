/**
 * Шапка карточки: где лот в пути и чья подпись.
 *
 * Обе полосы вне вкладок намеренно: на какой бы вкладке человек ни стоял,
 * ответ на вопрос «что с закупкой» у него перед глазами. Сведения о самой
 * закупке отсюда уехали во вкладку «Общая информация» — их набралось за
 * двадцать, и полосой сверху они занимали пол-экрана.
 */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  cardsApi,
  OFF_TRACK,
  type ApprovalKind,
  type Card,
  type LotStatus,
  type Sign,
} from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, Input, cx } from "@/ui";
import { stamp } from "./kit";
import { StatusModal } from "./StatusModal";

/**
 * Где лот сейчас — и чем это изменить.
 *
 * Одно состояние словом и кнопка рядом. Дорожка шагов отсюда убрана: она
 * рисовала процесс таким, каким его задумали, а переходы у нас свободные —
 * из любого состояния в любое. Полоса из одиннадцати чёрточек обещала
 * порядок, которого нет: лот уходит с «Разбора» сразу в «Не участвуем», и
 * подсвеченный «шаг 3 из 11» на этом становился неправдой.
 *
 * Смена — окном, а не списком на месте. Состояний четырнадцать, и разложить
 * их в полосе можно только сокращениями; в окне у каждого стоит объяснение,
 * что оно значит, а два перехода из четырнадцати требуют условий — пяти
 * подписей и причины отказа.
 */
export function Summary({
  card,
  onDone,
}: {
  card: Card;
  onDone: (fresh: Card) => void;
}) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState<LotStatus | null>(null);
  const [why, setWhy] = useState("");
  const [trouble, setTrouble] = useState("");

  const move = useMutation({
    mutationFn: (input: { to: LotStatus; reason: string }) =>
      cardsApi.move(card.id, input.to, input.reason),
    onSuccess: (fresh) => {
      setOpen(false);
      setAsking(null);
      setWhy("");
      setTrouble("");
      onDone(fresh);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const press = (to: LotStatus) => {
    setTrouble("");
    setOpen(false);
    // «Не участвуем» без причины — вопрос без ответа через месяц. Спрашиваем
    // до перехода, а не отказом после.
    if (to === "skipped") setAsking(to);
    else move.mutate({ to, reason: "" });
  };

  return (
    <section className="rounded-[10px] border border-hairline bg-surface px-[15px] py-3">
      {/* Порядок как в макете: где лот, сколько осталось, куда ведёт полоса,
          чем это менять. Отсчёт крупным числом и без заливки — цифры и есть
          главное на этой строке, а плашка вокруг них спорит со статусом
          слева. */}
      <div className="flex flex-wrap items-center gap-4">
        <span
          className={cx(
            "inline-flex h-[26px] shrink-0 items-center gap-1.5 rounded-[7px] px-2.5",
            "text-[12.5px] font-medium",
            OFF_TRACK.includes(card.status)
              ? "bg-plane text-ink-secondary"
              : "bg-plane text-ink",
          )}
        >
          {/* Точка рядом со словом, а не вместо: цвет сам по себе не отличает
              «идёт» от «сошёл с дистанции». */}
          <span
            aria-hidden
            className={cx(
              "h-[7px] w-[7px] rounded-full",
              OFF_TRACK.includes(card.status) ? "bg-ink-muted" : "bg-ink",
            )}
          />
          {card.status_name}
        </span>

        <Deadline card={card} />

        <Button
          variant="secondary"
          onClick={() => setOpen(true)}
          disabled={move.isPending}
        >
          {move.isPending ? "Переводим…" : "Изменить статус"}
        </Button>
      </div>

      {asking && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-hairline pt-2.5">
          <Input
            value={why}
            onChange={(event) => setWhy(event.target.value)}
            placeholder="Почему не участвуем? Через месяц это спросят"
            className="min-w-64 flex-1"
            autoFocus
          />
          <Button
            variant="danger"
            onClick={() => move.mutate({ to: asking, reason: why })}
            disabled={!why.trim() || move.isPending}
          >
            Не участвуем
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setAsking(null);
              setWhy("");
            }}
          >
            Отмена
          </Button>
        </div>
      )}

      {trouble && <p className="mt-2 text-sm text-critical">{trouble}</p>}

      {open && (
        <StatusModal
          card={card}
          onClose={() => setOpen(false)}
          onPick={press}
        />
      )}
    </section>
  );
}

/**
 * Сколько осталось до конца приёма — тикающими цифрами.
 *
 * Большим — остаток, мелким под ним дата и время. Спрашивают именно остаток:
 * «успеваем ли», а не «какое число». Дата рядом нужна, чтобы назначить
 * созвон и посчитать, что успеет снабжение, — но читают её вторым взглядом.
 *
 * Тикает каждую секунду. Срок приходит с сервера строкой «0 дн., 2 ч.,
 * 38 мин.» и застывает: карточку держат открытой часами, и человек,
 * вернувшийся к ней после обеда, видел вчерашний остаток и верил ему. В
 * последний час это разница между поданной заявкой и неподанной.
 *
 * Считается в браузере от даты окончания, а не пересчитывается запросом:
 * запрос раз в секунду — это три с половиной тысячи обращений за час
 * открытой вкладки ради числа, которое можно вычесть на месте.
 *
 * Срочность — тремя ступенями: сутки, полсмены и дальше. Красится сам отсчёт,
 * а не полоса под ним: полосу убрали — она показывала долю пройденного от
 * взятия в работу, а решают по остатку.
 *
 * Ступеней три, а не пять: цвет в одиночку при дальтонизме не различает
 * оранжевое от красного, и пять оттенков одного значили ровно то же, что три.
 * Сами цифры при этом тикают, и «00:40:12» читается однозначно.
 */
function Deadline({ card }: { card: Card }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  if (!card.deadline) return null;

  const end = new Date(card.deadline).getTime();
  const left = Math.max(0, end - now);
  const step = urgency(left);

  return (
    <>
      {/* Подпись над числом: «15:57:42» само по себе не говорит, до чего это.
          До конца приёма, а не до подписей — их срок строкой правее. */}
      <span className="w-[190px] shrink-0">
        <span className="block text-[11.5px] text-ink-muted">
          До конца приёма заявок
        </span>
        <span
          className={cx(
            "mt-1 block text-[27px] leading-none font-semibold tracking-[-0.03em] tabular-nums",
            step.text,
          )}
        >
          {left === 0 ? "приём закрыт" : clock(left)}
        </span>
      </span>

      {/* Обе даты одной строкой. Подписи собирают на два часа раньше приёма, и
          держать это число в другом месте экрана значит заставить человека
          складывать в уме на срочной работе.

          Полосы пройденного под ними больше нет. Она показывала долю от
          взятия в работу до окончания приёма — величину, которой никто не
          пользуется: решают по остатку слева, а он и так набран крупно. Зато
          сама полоса тянулась во всю ширину и притягивала взгляд к тому, что
          ничего не решает; освободившееся место отдано датам, набранным
          крупнее — их читают вторым взглядом, но читают. */}
      <span className="min-w-[120px] flex-1">
        <span className="block text-[13.5px] leading-snug text-ink-secondary tabular-nums">
          приём до <b className="font-semibold text-ink">{stamp(card.deadline)}</b>
          {card.approve_by && (
            <>
              {" · подписи до "}
              <b className="font-semibold text-ink">{stamp(card.approve_by)}</b>
            </>
          )}
        </span>
      </span>
    </>
  );
}

/**
 * Остаток часами, минутами и секундами.
 *
 * Секунды нужны: в последний час на них и смотрят. Часы не переводятся в дни —
 * «48:12:33» читается как «двое суток» без деления в уме, а «2 дн. 0 ч.»
 * заставляет вспоминать, сколько там осталось часов.
 */
function clock(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}:${pad(seconds % 60)}`;
}

const HOUR = 60 * 60 * 1000;

/**
 * Ступени срочности по остатку времени.
 *
 * Пороги те, что называют вслух: сутки, полсмены, три часа, час. Ниже часа
 * заявку уже не собирают заново — успевают только приложить готовое, и об
 * этом надо кричать.
 *
 * `loud` — залитая плашка вместо цветного текста. С трёх часов и ниже строка
 * должна быть видна боковым зрением, потому что смотрят в этот момент не на
 * неё, а на спецификацию.
 */
function urgency(left: number): { text: string } {
    if (left < 12 * HOUR) return { text: "text-critical" };
    if (left < 24 * HOUR) return { text: "text-warning" };
    return { text: "text-ink" };
}

/**
 * Согласование: пять подписей в ряд.
 *
 * Раньше это были пять строк, и зашедший подписать искал среди них свою.
 * Теперь пять колонок читаются разом, а тому, чья подпись нужна, показана
 * кнопка — одно нажатие вместо поиска.
 *
 * Порядок всегда один: менеджер, снабжение, юрист, технолог, сборщик.
 * Перестановка заставляет читать полосу заново каждый раз.
 */
function Slot({ sign }: { sign: Sign }) {
  const ok = sign.state === "approved";
  const no = sign.state === "rejected";

  return (
    <li>
      <span
        title={
          ok
            ? `${sign.name}: согласовал ${sign.by}${sign.at ? `, ${stamp(sign.at)}` : ""}`
            : no
              ? `${sign.name}: отклонил ${sign.by}${sign.note ? ` — ${sign.note}` : ""}`
              : `${sign.name}: подписи нет`
        }
        className={cx(
          "inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[12.5px]",
          ok
            ? "border-good/40 bg-good/10 text-good"
            : no
              ? "border-critical/40 bg-critical/10 text-critical"
              : "border-hairline bg-surface text-ink-secondary",
        )}
      >
        {ok && (
          <svg
            width="10"
            height="10"
            viewBox="0 0 12 12"
            fill="none"
            aria-hidden
          >
            <path
              d="M2.6 6.3 4.8 8.5 9.4 3.7"
              stroke="currentColor"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
        {no && <span aria-hidden>✕</span>}
        {sign.name}
      </span>
    </li>
  );
}

export function Approval({
  card,
  onDone,
}: {
  card: Card;
  onDone: (fresh: Card) => void;
}) {
  const [refusing, setRefusing] = useState<ApprovalKind | null>(null);
  const [why, setWhy] = useState("");
  const [trouble, setTrouble] = useState("");

  const mine = card.approvals.find(
    (sign) => sign.can_sign && sign.state === "waiting",
  );
  const signed = card.approvals.filter(
    (sign) => sign.state === "approved",
  ).length;
  const mySigned = card.approvals.find(
    (sign) => sign.can_sign && sign.state !== "waiting",
  );
  const refused = card.approvals.filter((sign) => sign.state === "rejected");

  const put = useMutation({
    mutationFn: (input: {
      kind: ApprovalKind;
      state: "approved" | "rejected";
      note: string;
    }) => cardsApi.sign(card.id, input.kind, input.state, input.note),
    onSuccess: (fresh) => {
      setRefusing(null);
      setWhy("");
      setTrouble("");
      onDone(fresh);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  return (
    /* Полосой во всю ширину колонки и с прилипанием к её низу, а не карточкой
       в потоке. Подписывают в конце работы, но искать подписи прокруткой на
       третьем экране — то, из-за чего согласование и собиралось по полдня:
       человек не находил, где это делается, и спрашивал в переписке. */
    <section
      className={cx(
        "sticky bottom-0 z-[5] mt-auto shrink-0 border-t border-hairline bg-surface",
        "shadow-[0_-6px_18px_rgba(14,22,32,.05)]",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-[14px] gap-y-2 px-[18px] py-[11px]">
        <span className="shrink-0">
          <span className="block text-[13.5px] font-semibold tracking-[-0.01em] text-ink">
            Готов к участию
          </span>
          <span className="block text-[11.5px] text-ink-muted tabular-nums">
            {signed} из {card.approvals.length} подписей
            {!card.approved && " · без пяти статус недоступен"}
          </span>
        </span>

        {/* Пять плашек вместо пяти колонок таблицы. Колонки занимали полосу в
            полтора сантиметра ради пяти слов, а вопрос к ним один: чьей
            подписи ещё нет. */}
        <ul className="flex flex-wrap gap-1.5">
          {card.approvals.map((sign) => (
            <Slot key={sign.kind} sign={sign} />
          ))}
        </ul>

        {mine && !refusing && (
          <span className="ml-auto flex shrink-0 items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => setRefusing(mine.kind)}
              disabled={put.isPending}
            >
              Отклонить
            </Button>
            <Button
              variant="primary"
              onClick={() =>
                put.mutate({ kind: mine.kind, state: "approved", note: "" })
              }
              disabled={put.isPending}
            >
              Подписать за «{mine.name}»
            </Button>
          </span>
        )}
        {!mine && mySigned && (
          <span className="ml-auto shrink-0 text-[12.5px] text-ink-muted">
            вы {mySigned.state === "approved" ? "подписали" : "отклонили"}{" "}
            {stamp(mySigned.at)}
          </span>
        )}
      </div>

      {/* Отказ разворачивается сам: причина нужна тому, кто пришёл чинить, а
          не спрятана под наведением. */}
      {refused.map((sign) => (
        <p
          key={sign.kind}
          className="border-t border-critical/25 bg-critical/5 px-5 py-2.5 text-sm text-ink"
        >
          <span className="font-medium text-critical">
            Отказ {sign.by}
            {sign.at && `, ${stamp(sign.at)}`}:
          </span>{" "}
          {sign.note}
        </p>
      ))}

      {refusing && (
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline bg-plane px-5 py-3">
          <Input
            value={why}
            onChange={(event) => setWhy(event.target.value)}
            placeholder="Что мешает согласовать: без причины подпись «нет» не объясняет, что чинить"
            className="min-w-64 flex-1"
            autoFocus
          />
          <Button
            variant="danger"
            onClick={() =>
              put.mutate({ kind: refusing, state: "rejected", note: why })
            }
            disabled={!why.trim() || put.isPending}
          >
            Отклонить
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setRefusing(null);
              setWhy("");
            }}
          >
            Отмена
          </Button>
        </div>
      )}

      {trouble && (
        <p className="border-t border-hairline px-5 py-2 text-sm text-critical">
          {trouble}
        </p>
      )}
    </section>
  );
}
