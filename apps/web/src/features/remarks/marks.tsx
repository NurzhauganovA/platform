/**
 * Как показываются состояния обсуждения.
 *
 * Значков нет — их нет нигде в платформе. Состояние читается словом, цветом и
 * положением, и это не аскетизм: набор картинок из чужой библиотеки не
 * совпадает по весу и посадке с текстом рядом, а нарисованный «огонёк»
 * рядом с суммой в тендере выглядит игрушечно там, где решают на миллионы.
 *
 * Роль цвета вспомогательная. Он ускоряет поиск глазами, но смысл несёт
 * слово: при дальтонизме «отправлено» и «отклонили» неразличимы, а решения по
 * ним разные — по первому ждут, по второму пишут жалобу.
 */

import { cx } from "@/ui";
import type { Outcome, Remark, Stage } from "@/api/remarks";
import { Passed } from "@/features/cards/kit";

/**
 * Полоса этапа — вертикальная черта слева у строки списка.
 *
 * Цвет без текста здесь допустим потому, что он не единственный носитель:
 * этап тут же написан словом. Полоса нужна, чтобы список читался столбцом, а
 * не строка за строкой.
 */
export const STAGE_RULE: Record<Stage, string> = {
  drafting: "bg-baseline",
  moderation: "bg-series-4",
  lawyers: "bg-series-1",
  sent: "bg-series-3",
  not_needed: "bg-hairline",
};

const STAGE_TEXT: Record<Stage, string> = {
  drafting: "text-ink-muted",
  moderation: "text-ink",
  lawyers: "text-series-1",
  sent: "text-ink-secondary",
  not_needed: "text-ink-muted",
};

const OUTCOME_TEXT: Record<Outcome, string> = {
  waiting: "text-ink-muted",
  accepted: "text-good",
  rejected: "text-serious",
  closed: "text-ink-muted",
  complaint: "text-critical",
};

/** Этап работы, словом. Приглушённый, если делать по нему нечего. */
export function StageWord({ remark }: { remark: Remark }) {
  return (
    <span className={cx("text-sm whitespace-nowrap", STAGE_TEXT[remark.stage])}>
      {remark.stage_name}
    </span>
  );
}

/**
 * Итог у заказчика. Только у отправленного: у ненаправленного «ждём ответа»
 * означало бы, что письмо ушло.
 */
export function OutcomeWord({ remark }: { remark: Remark }) {
  if (remark.stage !== "sent") return null;
  return (
    <span
      className={cx(
        "text-sm whitespace-nowrap",
        OUTCOME_TEXT[remark.outcome],
        remark.outcome === "complaint" && "font-medium",
      )}
    >
      {remark.outcome_name}
    </span>
  );
}

/**
 * Срок. Цифра крупнее подписи: по ней сортируют глазами, а сортируют по
 * сроку чаще всего.
 *
 * Просроченное и горящее выглядят по-разному, а не оттенками одного: по
 * первому писать поздно, по второму ещё успеть, и это разные действия.
 */
export function Deadline({ remark }: { remark: Remark }) {
  if (!remark.left) {
    return <span className="text-sm text-ink-muted tabular-nums">—</span>;
  }
  if (remark.overdue)
    return (
      <Passed
        submitted={remark.stage === "sent"}
        done="Срок прошёл, но замечание заказчику отправлено"
        missed="Срок обсуждения прошёл, замечание заказчику не отправлено"
        className="text-sm"
      />
    );
  return (
    <span
      className={cx(
        "text-sm tabular-nums whitespace-nowrap",
        remark.burning ? "font-semibold text-critical" : "text-ink-secondary",
      )}
    >
      {remark.left}
    </span>
  );
}

/**
 * Что делает модель прямо сейчас.
 *
 * Готовое не отмечается ничем: отметка у каждой строки перестаёт выделять.
 * Пока идёт — тонкая пульсирующая черта, а не вращающийся круг: круг в
 * строке таблицы дёргает глаз сильнее, чем стоит эта новость.
 */
export function WritingNote({ remark }: { remark: Remark }) {
  if (remark.writing === "ready") return null;
  if (remark.writing === "failed") {
    return <span className="text-sm text-critical">не написалось</span>;
  }
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-muted">
      <span className="h-px w-6 animate-pulse bg-series-1" aria-hidden />
      {remark.writing === "queued" ? "в очереди" : "модель пишет"}
    </span>
  );
}
