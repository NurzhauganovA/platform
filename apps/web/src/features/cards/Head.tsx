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
import { TZ } from "@/features/worklist/format";
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
    <section className="rounded-[10px] border border-hairline bg-surface px-5 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Deadline card={card} />

        <span
          className={cx(
            "inline-flex items-center gap-2 rounded-full px-3 py-1",
            OFF_TRACK.includes(card.status)
              ? "bg-plane text-ink-secondary"
              : "bg-series-1/10 text-ink",
          )}
        >
          {/* Значок рядом со словом, а не вместо: цвет сам по себе не
              отличает «идёт» от «сошёл с дистанции». */}
          <span aria-hidden className="text-xs">
            {OFF_TRACK.includes(card.status) ? "■" : "●"}
          </span>
          <span className="text-sm font-semibold">{card.status_name}</span>
        </span>

        <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
          {hint(card)}
        </span>

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
 * Срочность — лестницей, а не одним порогом. Раньше сутки красили цифры в
 * красный и на этом всё: «осталось 23 часа» и «осталось 40 минут» выглядели
 * одинаково, а это разные дни работы. Теперь у каждой ступени своя плашка и
 * своё слово рядом с цифрами — слово, потому что цвет в одиночку при
 * дальтонизме не отличает оранжевое от красного.
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
    <span
      className={cx(
        "inline-flex items-baseline gap-2.5 rounded-[10px] px-3 py-1.5",
        step.box,
      )}
      title="До конца приёма заявок"
    >
      <span
        className={cx(
          "leading-none font-bold tabular-nums",
          step.loud ? "text-2xl" : "text-lg font-semibold",
        )}
      >
        {left === 0 ? "ПРИЁМ ЗАКРЫТ" : spell(left)}
      </span>
      {step.word && (
        <span className="text-xs font-semibold whitespace-nowrap uppercase">
          {step.word}
        </span>
      )}
      <span
        className={cx(
          "text-xs whitespace-nowrap",
          step.loud ? "opacity-80" : "text-ink-muted",
        )}
      >
        {when(card.deadline)}
      </span>
    </span>
  );
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
function urgency(left: number): { box: string; word: string; loud: boolean } {
  // Слова рядом нет: «ПРИЁМ ЗАКРЫТ» крупным и «срок вышел» мелким — одно и
  // то же дважды, а место в шапке занимают оба.
  if (left === 0)
    return { box: "bg-critical text-white", word: "", loud: true };
  if (left < HOUR)
    return { box: "bg-critical text-white", word: "меньше часа", loud: true };
  if (left < 3 * HOUR)
    return {
      box: "bg-critical text-white",
      word: "меньше 3 часов",
      loud: true,
    };
  if (left < 6 * HOUR)
    return {
      box: "border border-critical/50 bg-critical/10 text-critical",
      word: "меньше 6 часов",
      loud: false,
    };
  if (left < 12 * HOUR)
    return {
      box: "border border-serious/60 bg-serious/15 text-ink",
      word: "меньше 12 часов",
      loud: false,
    };
  if (left < 24 * HOUR)
    return {
      box: "border border-warning/60 bg-warning/15 text-ink",
      word: "меньше суток",
      loud: false,
    };
  return { box: "text-ink", word: "", loud: false };
}

/**
 * Остаток словами: «2 дн. 04:17:09».
 *
 * Секунды показываются всегда, а не только в последний час: полоса цифр,
 * которая меняется на глазах, сама говорит, что счёт идёт. Застывшие «2 ч.
 * 17 мин.» от неё неотличимы, пока не посмотришь дважды.
 */
function spell(ms: number): string {
  const all = Math.floor(ms / 1000);
  const days = Math.floor(all / 86_400);
  const hours = Math.floor((all % 86_400) / 3600);
  const minutes = Math.floor((all % 3600) / 60);
  const seconds = all % 60;
  const clock = [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return days > 0 ? `${days} дн. ${clock}` : clock;
}

/** Что сейчас происходит, словом. Одно название состояния этого не объясняет. */
function hint(card: Card): string {
  if (card.status === "approval") return "собираем пять подписей";
  if (card.status === "discussion") return "пишем замечание к спецификации";
  if (card.status === "analysis") return "считаем себестоимость и решаем";
  if (card.status === "ready") return "подписи собраны, можно подавать";
  if (card.status === "awaiting") return "заявка подана, ждём результат";
  if (card.status === "skipped") return card.skip_reason || "решили пропустить";
  return "";
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
    <section className="overflow-hidden rounded-[10px] border border-hairline bg-surface">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-hairline px-5 py-2.5">
        <h2 className="text-sm font-semibold text-ink">Согласование</h2>
        <p className="text-sm text-ink-muted">
          {signed} из {card.approvals.length}
          {!card.approved && " · без пяти «Готов к участию» недоступен"}
        </p>

        {mine && !refusing && (
          <span className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
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
          <p className="ml-auto text-sm text-ink-muted">
            вы {mySigned.state === "approved" ? "подписали" : "отклонили"}{" "}
            {when(mySigned.at)}
          </p>
        )}
      </header>

      <div className="grid grid-cols-5">
        {card.approvals.map((sign, index) => (
          <Column
            key={sign.kind}
            sign={sign}
            last={index === card.approvals.length - 1}
          />
        ))}
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
            {sign.at && `, ${when(sign.at)}`}:
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

function Column({ sign, last }: { sign: Sign; last: boolean }) {
  const word =
    sign.state === "approved"
      ? "согласовал"
      : sign.state === "rejected"
        ? "отклонил"
        : "ждём";
  const look =
    sign.state === "approved"
      ? "text-good"
      : sign.state === "rejected"
        ? "text-critical"
        : "text-ink-muted";

  return (
    <div
      className={cx("min-w-0 px-5 py-3", !last && "border-r border-hairline")}
    >
      <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">
        {sign.name}
      </p>
      <p className={cx("mt-1 text-sm", look)}>{word}</p>
      <p className="mt-0.5 truncate text-xs text-ink-muted">
        {sign.by ? `${sign.by} · ${when(sign.at)}` : "подписи нет"}
      </p>
    </div>
  );
}

/** «02.09 09:14» — короче полной даты, а год у лота один. */
function when(at: string): string {
  if (!at) return "";
  return new Date(at).toLocaleString("ru", {
    // Пояс раздела, а не браузера: сотрудник в командировке смотрит на тот же
    // срок, что и коллеги в офисе, и «до 14:00» должно значить одно и то же.
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
