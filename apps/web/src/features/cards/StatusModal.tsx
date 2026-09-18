/**
 * Все состояния лота в одном окне.
 *
 * Переходы свободные: перевести можно откуда угодно куда угодно. Четырнадцать
 * кнопок в узкой колонке справа стали бы списком настроек, поэтому там
 * остались только ближайшие, а полный набор живёт здесь.
 *
 * Разложено по смыслу и с подписью у каждого: «Ожидаем оплату» и «Ожидаем
 * итоги» различаются одним словом, и без пояснения в них промахиваются.
 * Поиск — потому что четырнадцать это уже больше, чем окидывают взглядом.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cardsApi, FLOW, type Card, type LotStatus } from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, Input, cx } from "@/ui";

export const STATUS_NAMES: Record<LotStatus, string> = {
  work: "В работе",
  approval: "На согласовании",
  submission: "Подача",
  waiting: "Ожидание протокола итогов",
  done: "Завершённый",
};

const ABOUT: Record<LotStatus, string> = {
  work: "обсуждение, разбор, юрист, технолог, снабжение",
  approval: "собираем пять подписей",
  submission: "подписи собраны, готовим и подаём заявку",
  waiting: "заявка подана, ждём протокол",
  done: "работа кончилась; чем — в итоге протокола",
};

// Группы остались, хотя состояний шесть: они отвечают на «до подачи или
// после», и человек ищет нужное глазами по этой границе, а не по алфавиту.
const GROUPS: { title: string; keys: LotStatus[] }[] = [
  { title: "До подачи", keys: ["work", "approval"] },
  { title: "Подача и итоги", keys: ["submission", "waiting", "done"] },
];

export function StatusModal({
  card,
  onClose,
  onPick,
}: {
  card: Card;
  onClose: () => void;
  onPick: (to: LotStatus) => void;
}) {
  const [needle, setNeedle] = useState("");
  // Второй шаг: «Завершённый» без ответа «чем кончилось» — это статус,
  // который ничего не говорит. Через месяц по нему не отличить выигранную
  // закупку от той, мимо которой прошли, а отчёт строится именно по этому.
  const [ending, setEnding] = useState(false);

  // Esc закрывает: окно поверх работы, и выход из него должен быть там же,
  // где его ищут.
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", press);
    return () => window.removeEventListener("keydown", press);
  }, [onClose]);

  const step = FLOW.findIndex((item) => item.key === card.status);
  const ahead = step >= 0 ? FLOW[step + 1]?.key : undefined;
  const search = needle.trim().toLowerCase();
  const fits = (key: LotStatus) =>
    !search ||
    STATUS_NAMES[key].toLowerCase().includes(search) ||
    ABOUT[key].includes(search);

  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center bg-ink/25 px-6 py-20"
      role="dialog"
      aria-modal="true"
      aria-label="Сменить статус"
      onClick={onClose}
    >
      <div
        className="w-full max-w-4xl overflow-hidden rounded-[12px] border border-hairline bg-surface shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-hairline px-5 py-3">
          <h2 className="text-[15px] font-semibold text-ink">
            Сменить статус · {card.code}
          </h2>
          <p className="text-sm text-ink-muted">
            сейчас {card.status_name} · переходы свободные, из любого состояния
            в любое
          </p>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-sm text-series-1 hover:underline"
          >
            Закрыть
          </button>
        </header>

        {ending ? (
          <Ending
            card={card}
            onBack={() => setEnding(false)}
            onDone={onClose}
          />
        ) : (
          <>
            <div className="px-5 py-3">
              <Input
                value={needle}
                onChange={(event) => setNeedle(event.target.value)}
                placeholder="Поиск: «догов», «оплат»…"
                className="max-w-sm"
                autoFocus
              />
            </div>

            <div className="grid grid-cols-4 gap-4 px-5 pb-4">
              {GROUPS.map((group) => (
                <div key={group.title}>
                  <p className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
                    {group.title}
                  </p>
                  <div className="space-y-2">
                    {group.keys.filter(fits).map((key) => (
                      <Choice
                        key={key}
                        status={key}
                        here={key === card.status}
                        ahead={key === ahead}
                        allowed={card.can.includes(key)}
                        card={card}
                        onPick={(to) =>
                          to === "done" ? setEnding(true) : onPick(to)
                        }
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <p className="border-t border-hairline px-5 py-3 text-sm text-ink-muted">
              Два условия, и оба про деньги: «Подача» ждёт все пять подписей,
              «Завершённый» — ответ, чем кончилось. Условие видно до нажатия, а
              не отказом после.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Чем кончилась закупка — второй шаг перевода в «Завершённый».
 *
 * Спрашиваем здесь, а не отдельным блоком в колонке. Прежний переключатель
 * «Участвуем? Да/Нет» стоял в правом столбце и упирался в плавающую кнопку
 * переписки — нажать его было делом удачи. А вопрос у него был тот же:
 * закупка кончилась, и надо сказать чем.
 *
 * Выигрыш и проигрыш отдельно от остальных и только у поданной заявки: у них
 * своя дверь, она требует цены и победителя. «Выиграли» у лота, который не
 * подавали, означало бы итоги закупки, в которой мы не участвовали.
 */
function Ending({
  card,
  onBack,
  onDone,
}: {
  card: Card;
  onBack: () => void;
  onDone: () => void;
}) {
  const [outcome, setOutcome] = useState("");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [winner, setWinner] = useState("");
  const [trouble, setTrouble] = useState("");

  const { data: picks } = useQuery({
    queryKey: ["card-stages"],
    queryFn: cardsApi.stages,
    staleTime: Infinity,
  });
  const client = useQueryClient();

  const всё = picks?.done ?? [];
  const наши = всё.filter((item) => item.by_decision);
  // Протокольные итоги предлагаем только у поданного лота: иначе это итоги
  // закупки, в которой мы не участвовали.
  const протокол = card.submitted
    ? всё.filter((item) => !item.by_decision)
    : [];
  const выбран = всё.find((item) => item.key === outcome);
  const нужна = Boolean(выбран?.needs_reason);

  const save = useMutation({
    mutationFn: () =>
      выбран?.by_decision
        ? cardsApi.finish(card.id, outcome, reason.trim())
        : cardsApi.result(
            card.id,
            amount ? Number(amount) : null,
            winner.trim(),
            outcome as never,
          ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["card", card.id] });
      void client.invalidateQueries({ queryKey: ["cards"] });
      onDone();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const готово = Boolean(outcome) && (!нужна || reason.trim() !== "");

  return (
    <div className="px-5 py-4">
      <p className="mb-1 text-sm font-medium text-ink">Чем кончилось?</p>
      <p className="mb-3 text-xs text-ink-muted">
        Статус «Завершённый» без ответа ничего не говорит: через месяц по нему
        не отличить выигранную закупку от той, мимо которой прошли.
      </p>

      {протокол.length > 0 && (
        <Row title="По протоколу">
          {протокол.map((item) => (
            <Pill
              key={item.key}
              on={outcome === item.key}
              onClick={() => setOutcome(item.key)}
            >
              {item.title}
            </Pill>
          ))}
        </Row>
      )}

      <Row title={card.submitted ? "Без протокола" : "Заявку не подавали"}>
        {наши.map((item) => (
          <Pill
            key={item.key}
            on={outcome === item.key}
            onClick={() => {
              setOutcome(item.key);
              // Слово сразу в поле: его дописывают, а не заменяют — «код не
              // подходит» сам по себе ответ неполный.
              setReason((был) =>
                !был || всё.some((one) => one.title === был.trim())
                  ? item.needs_reason
                    ? item.title
                    : ""
                  : был,
              );
            }}
          >
            {item.title}
          </Pill>
        ))}
      </Row>

      {выбран?.by_decision && (
        <label className="mt-3 block">
          <span className="mb-1 block text-xs text-ink-muted">
            {нужна ? "Причина" : "Подробности — если есть"}
          </span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={2}
            placeholder="Выберите причину выше или напишите свою"
            className={cx(
              "w-full max-w-xl resize-y rounded-[8px] border border-baseline bg-surface px-2.5 py-2",
              "text-[13px] leading-relaxed text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
        </label>
      )}

      {выбран && !выбран.by_decision && (
        <div className="mt-3 flex flex-wrap gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-ink-muted">
              {outcome === "won"
                ? "За сколько выиграли, ₸"
                : "Цена победителя, ₸"}
            </span>
            <Input
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="8 660 625"
              className="w-44 tabular-nums"
            />
          </label>
          {outcome === "lost" && (
            <label className="block">
              <span className="mb-1 block text-xs text-ink-muted">
                Кто взял
              </span>
              <Input
                value={winner}
                onChange={(event) => setWinner(event.target.value)}
                placeholder="ТОО «Соседи»"
                className="w-64"
              />
            </label>
          )}
        </div>
      )}

      {trouble && <p className="mt-2 text-sm text-critical">{trouble}</p>}

      <div className="mt-4 flex items-center gap-2">
        <Button
          variant="primary"
          disabled={!готово || save.isPending}
          onClick={() => save.mutate()}
          title={готово ? undefined : "Выберите итог и напишите причину"}
        >
          {save.isPending ? "Завершаем…" : "Завершить"}
        </Button>
        <Button variant="secondary" onClick={onBack}>
          Назад к состояниям
        </Button>
      </div>
    </div>
  );
}

function Row({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 w-[8.5rem] shrink-0 text-xs text-ink-muted">
        {title}
      </span>
      {children}
    </div>
  );
}

function Pill({
  children,
  on,
  onClick,
}: {
  children: React.ReactNode;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cx(
        "rounded-[7px] border px-2.5 py-1 text-[12.5px] transition",
        on
          ? "border-ink bg-ink text-surface"
          : "border-hairline text-ink-secondary hover:bg-plane",
      )}
    >
      {children}
    </button>
  );
}

function Choice({
  status,
  here,
  ahead,
  allowed,
  card,
  onPick,
}: {
  status: LotStatus;
  here: boolean;
  ahead: boolean;
  allowed: boolean;
  card: Card;
  onPick: (to: LotStatus) => void;
}) {
  const signed = card.approvals.filter(
    (sign) => sign.state === "approved",
  ).length;
  // Правило осталось одно и оно про деньги: подавать без пяти подписей — это
  // участие в закупке, товара под которую нет. Стояло оно на «Готов к
  // участию»; теперь на «Подаче» — состоянии, из которого заявка и уходит.
  // Причину спрашивает решение об участии, а не перевод: состояния «Не
  // участвуем» больше нет.
  const why =
    status === "submission" && !allowed && !here
      ? `нужны все пять подписей — сейчас ${signed}`
      : "";

  return (
    <button
      type="button"
      disabled={here || !allowed}
      onClick={() => onPick(status)}
      className={cx(
        "w-full rounded-[8px] border px-3 py-2 text-left transition",
        here
          ? "border-series-1 bg-series-1/10"
          : ahead && allowed
            ? "border-series-1/50 bg-series-1/5 hover:bg-series-1/10"
            : why && !allowed
              ? "border-warning/40 bg-warning/5"
              : allowed
                ? "border-hairline hover:border-baseline hover:bg-plane"
                : "cursor-not-allowed border-hairline opacity-60",
      )}
    >
      <span className="flex items-baseline gap-2">
        <span className="text-sm font-medium text-ink">
          {STATUS_NAMES[status]}
        </span>
        {here && <span className="ml-auto text-xs text-series-1">сейчас</span>}
        {ahead && !here && (
          <span className="ml-auto text-xs text-series-1">следующий</span>
        )}
        {!here && !ahead && why && !allowed && (
          <span className="ml-auto text-xs text-warning">условие</span>
        )}
      </span>
      <span className="mt-0.5 block text-xs text-ink-muted">
        {here ? "текущее состояние" : ABOUT[status]}
      </span>
      {why && (
        <span
          className={cx(
            "mt-0.5 block text-xs",
            allowed ? "text-ink-muted" : "text-critical",
          )}
        >
          {why}
        </span>
      )}
    </button>
  );
}
