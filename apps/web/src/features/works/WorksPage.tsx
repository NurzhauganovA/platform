/**
 * Раздел «В работе»: лоты, взятые в работу, и чьего хода ждут.
 *
 * Список разложен по тому, кому сейчас работать, а не по времени создания.
 * Сотрудник заходит сюда утром с одним вопросом — «что от меня», — и общий
 * список из тридцати строк отвечает на него хуже, чем три коротких: свои,
 * чужие, готовые.
 *
 * Внутри своих — дольше всех ждущие сверху. Неделя у одного отдела это уже не
 * «идёт работа», а «забыли», и такая строка не должна тонуть под свежими.
 *
 * Снабжению видно только переданное ему: до передачи там нечего смотреть, а
 * после возврата лот снова у разбора. Решает это сервер — прятать строки в
 * браузере значит отдать их в ответе.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { Role } from "@/api/tender";
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

export function WorksPage({ role }: { role: Role }) {
  const analysis = role === "analyst" || role === "admin";
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["works"],
    queryFn: worksApi.list,
  });

  if (isLoading)
    return (
      <>
        <PageHeader title="В работе" />
        <div className="px-8 py-6">
          <Spinner label="Смотрим, что в работе…" />
        </div>
      </>
    );

  if (isError || !data)
    return (
      <>
        <PageHeader title="В работе" />
        <div className="px-8 py-6">
          <Card className="px-5 py-4 text-sm text-ink-secondary">
            {error instanceof Error ? error.message : "Список не собрался"}
          </Card>
        </div>
      </>
    );

  // Чей ход — то же правило, что и на самом лоте: разбор работает, пока лот
  // не у снабжения, снабжение — пока он у него.
  const мой = (work: WorkListItem) =>
    analysis ? work.stage !== "supply" : work.stage === "supply";

  const свои = data
    .filter((work) => мой(work) && work.stage !== "returned")
    .sort(
      (left, right) => (right.waiting_days ?? 0) - (left.waiting_days ?? 0),
    );
  const чужие = data.filter((work) => !мой(work));
  const готовые = data.filter((work) => work.stage === "returned" && мой(work));

  return (
    <>
      <PageHeader
        title="В работе"
        subtitle="Лоты, по которым идёт работа между разбором и снабжением"
      />
      <div className="space-y-5 px-8 py-6">
        {!data.length ? (
          <Empty />
        ) : (
          <>
            <Group
              title="Ваш ход"
              hint="ждут вашей работы"
              works={свои}
              analysis={analysis}
              accent
              empty={
                analysis
                  ? "Всё передано снабжению — ждём цены"
                  : "Разбор пока ничего не передал"
              }
            />
            <Group
              title={analysis ? "У снабжения" : "У разбора"}
              hint="работает другой отдел"
              works={чужие}
              analysis={analysis}
            />
            <Group
              title="Готово к КП"
              hint="цены подтверждены, можно считать предложение"
              works={готовые}
              analysis={analysis}
            />
          </>
        )}
      </div>
    </>
  );
}

function Group({
  title,
  hint,
  works,
  analysis,
  accent,
  empty,
}: {
  title: string;
  hint: string;
  works: WorkListItem[];
  analysis: boolean;
  accent?: boolean;
  empty?: string;
}) {
  if (!works.length && !empty) return null;

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
        <h3
          className={cx(
            "text-sm font-semibold",
            accent ? "text-ink" : "text-ink-secondary",
          )}
        >
          {title}
        </h3>
        <span className="text-xs text-ink-muted">
          {works.length ? `${works.length} · ${hint}` : hint}
        </span>
      </div>

      {!works.length ? (
        <Card className="px-5 py-3 text-sm text-ink-muted">{empty}</Card>
      ) : (
        <Card
          className={cx(
            "overflow-hidden p-0",
            accent && "border-series-1/40 ring-1 ring-series-1/15",
          )}
        >
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-hairline bg-plane text-left text-xs text-ink-secondary">
                <th className="w-24 px-5 py-2.5 font-medium">Код</th>
                <th className="px-3 py-2.5 font-medium">Лот</th>
                <th className="w-20 px-3 py-2.5 text-right font-medium">
                  Позиций
                </th>
                {analysis && (
                  <th className="w-40 px-3 py-2.5 text-right font-medium">
                    Сумма, ₸
                  </th>
                )}
                <th className="w-40 px-3 py-2.5 font-medium">Где сейчас</th>
                <th className="w-36 px-5 py-2.5 font-medium">Ждёт</th>
              </tr>
            </thead>
            <tbody>
              {works.map((work) => (
                <Row key={work.id} work={work} analysis={analysis} />
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </section>
  );
}

function Row({ work, analysis }: { work: WorkListItem; analysis: boolean }) {
  const stage = STAGES[work.stage];
  const дней = work.waiting_days ?? 0;
  // Неделя у одного отдела — это уже не «идёт работа», а «забыли». Три дня —
  // ещё не тревога, но уже повод спросить.
  const тон =
    дней >= 7
      ? "font-medium text-critical"
      : дней >= 3
        ? "text-warning"
        : "text-ink";

  return (
    <tr className="border-b border-hairline last:border-0 hover:bg-plane">
      <td className="px-5 py-2.5 align-top">
        <Link
          to={`/tender/works/${work.id}`}
          className="font-medium tabular-nums text-series-1 hover:underline"
        >
          {work.code}
        </Link>
      </td>
      <td className="px-3 py-2.5 align-top">
        <Link to={`/tender/works/${work.id}`} className="text-ink">
          {work.title}
        </Link>
        {work.customer && (
          <div className="mt-0.5 text-xs text-ink-muted">{work.customer}</div>
        )}
      </td>
      <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
        {work.positions}
      </td>
      {analysis && (
        <td className="px-3 py-2.5 text-right align-top tabular-nums text-ink">
          {work.total === null ? "—" : money(work.total)}
        </td>
      )}
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
            <span className={тон}>
              {дней === 0 ? "сегодня" : `${дней} ${_days(дней)}`}
              {дней >= 7 && " — забыли?"}
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
        разборе закупки. Дальше по нему подтверждают поставщиков, пишут задание
        и передают снабжению.
      </p>
    </Card>
  );
}
