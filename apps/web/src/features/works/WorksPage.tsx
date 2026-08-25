/**
 * Раздел «В работе»: лоты, взятые в работу, и у кого они сейчас.
 *
 * Главный вопрос по этому списку не «что там», а «что стоит». Поэтому первым
 * читается состояние и сколько дней лот лежит у отдела, а не сумма и не
 * название: сумму смотрят, когда уже выбрали, что открыть.
 *
 * Снабжению видно только переданное ему: до передачи там нечего смотреть, а
 * после возврата лот снова у разбора. Решает это сервер — прятать строки в
 * браузере значит отдать их в ответе.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { worksApi, type WorkListItem, type WorkStage } from "@/api/worklist";
import { PageHeader } from "@/shell/AppShell";
import { Card, Spinner, cx, money } from "@/ui";
import { formatDate } from "@/features/worklist/format";

/** Как называется состояние и чьего хода ждут. */
export const STAGES: Record<
  WorkStage,
  { title: string; hint: string; tone: string }
> = {
  analysis: {
    title: "У разбора",
    hint: "выбирают поставщиков",
    tone: "bg-series-1/10 text-series-1",
  },
  supply: {
    title: "У снабжения",
    hint: "проверяют цены и сроки",
    tone: "bg-warning/15 text-warning",
  },
  returned: {
    title: "Вернулось",
    hint: "цены подтверждены",
    tone: "bg-good/15 text-good",
  },
};

export function WorksPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["works"],
    queryFn: worksApi.list,
  });

  return (
    <>
      <PageHeader
        title="В работе"
        subtitle="Лоты, по которым идёт работа между разбором и снабжением"
      />
      <div className="px-8 py-6">
        {isLoading ? (
          <Spinner label="Смотрим, что в работе…" />
        ) : isError ? (
          <Card className="px-5 py-4 text-sm text-ink-secondary">
            {error instanceof Error ? error.message : "Список не собрался"}
          </Card>
        ) : !data?.length ? (
          <Empty />
        ) : (
          <Card className="overflow-hidden p-0">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-hairline bg-plane text-left text-xs text-ink-secondary">
                  <th className="px-5 py-2.5 font-medium">Код</th>
                  <th className="px-3 py-2.5 font-medium">Лот</th>
                  <th className="px-3 py-2.5 text-right font-medium">
                    Позиций
                  </th>
                  <th className="px-3 py-2.5 text-right font-medium">
                    Сумма, ₸
                  </th>
                  <th className="px-3 py-2.5 font-medium">Где сейчас</th>
                  <th className="px-5 py-2.5 font-medium">Ждёт</th>
                </tr>
              </thead>
              <tbody>
                {data.map((work) => (
                  <Row key={work.id} work={work} />
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </>
  );
}

function Row({ work }: { work: WorkListItem }) {
  const stage = STAGES[work.stage];
  // Неделя у одного отдела — это уже не «идёт работа», а «забыли».
  const stalled = (work.waiting_days ?? 0) >= 7;

  return (
    <tr className="border-b border-hairline last:border-0 hover:bg-plane">
      <td className="px-5 py-2.5 align-top">
        <Link
          to={`/tender/works/${work.id}`}
          className="font-medium text-series-1 tabular-nums hover:underline"
        >
          {work.code}
        </Link>
      </td>
      <td className="px-3 py-2.5 align-top">
        <div className="text-ink">{work.title}</div>
        {work.customer && (
          <div className="mt-0.5 text-xs text-ink-muted">{work.customer}</div>
        )}
      </td>
      <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
        {work.positions}
      </td>
      <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
        {work.total === null ? "—" : money(work.total)}
      </td>
      <td className="px-3 py-2.5 align-top">
        <span
          className={cx(
            "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
            stage.tone,
          )}
        >
          {stage.title}
        </span>
        <div className="mt-0.5 text-xs text-ink-muted">{stage.hint}</div>
      </td>
      <td className="px-5 py-2.5 align-top text-xs">
        {work.waiting_days === null ? (
          <span className="text-ink-muted">—</span>
        ) : (
          <>
            <span
              className={stalled ? "font-medium text-critical" : "text-ink"}
            >
              {work.waiting_days === 0
                ? "сегодня"
                : `${work.waiting_days} ${_days(work.waiting_days)}`}
            </span>
            {work.sent_at && (
              <div className="mt-0.5 text-ink-muted">
                с {formatDate(work.sent_at)}
              </div>
            )}
          </>
        )}
      </td>
    </tr>
  );
}

function _days(count: number): string {
  const last = count % 10;
  const teen = count % 100 >= 11 && count % 100 <= 14;
  if (!teen && last === 1) return "день";
  if (!teen && last >= 2 && last <= 4) return "дня";
  return "дней";
}

function Empty() {
  return (
    <Card className="px-6 py-10 text-center">
      <p className="text-sm text-ink">Пока ничего не в работе.</p>
      <p className="mx-auto mt-1.5 max-w-lg text-sm text-ink-muted">
        Лот попадает сюда, когда отдел разбора нажимает «Взять в работу» в
        разборе закупки. Дальше по нему подтверждают поставщиков и передают
        снабжению.
      </p>
    </Card>
  );
}
