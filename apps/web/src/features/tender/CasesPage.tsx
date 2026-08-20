/**
 * Список закупок.
 *
 * Плотная таблица, а не карточки: тендерщик держит в работе десятки папок и
 * сравнивает их взглядом сверху вниз. Карточки на этом объёме превращают
 * список в бесконечную прокрутку.
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { tender, type CaseStatus } from "@/api/tender";
import { PageHeader } from "@/shell/AppShell";
import { Badge, Button, Card, EmptyState, Spinner, bytes } from "@/ui";

const STATUS: Record<
  CaseStatus,
  { title: string; tone: "neutral" | "info" | "good" | "warning" }
> = {
  draft: { title: "Черновик", tone: "neutral" },
  ready: { title: "Готова к разбору", tone: "info" },
  analyzing: { title: "Разбирается", tone: "warning" },
  analyzed: { title: "Разобрана", tone: "good" },
  archived: { title: "В архиве", tone: "neutral" },
};

export function CasesPage() {
  const { data: cases, isLoading } = useQuery({
    queryKey: ["cases"],
    queryFn: tender.cases,
  });

  const { data: health } = useQuery({
    queryKey: ["tender-health"],
    queryFn: tender.health,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <>
      <PageHeader
        title="Закупки"
        subtitle="Папки с документацией, которые мы разбираем"
        action={
          <Link to="/tender/cases/new">
            <Button variant="primary">Новая закупка</Button>
          </Link>
        }
      />

      <div className="space-y-4 px-8 py-6">
        {health && !health.ok && (
          <Card className="border-warning/40 bg-warning/10 px-5 py-3.5">
            <div className="flex items-start gap-2.5">
              <span aria-hidden className="mt-0.5 text-warning">
                ▲
              </span>
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink">
                  Не всё готово к разбору
                </div>
                <ul className="mt-1 space-y-0.5 text-sm text-ink-secondary">
                  {health.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </div>
            </div>
          </Card>
        )}

        <Card>
          {isLoading ? (
            <div className="px-5 py-8">
              <Spinner label="Загружаем закупки…" />
            </div>
          ) : !cases?.length ? (
            <EmptyState
              title="Пока ни одной закупки"
              description="Заведите закупку и выберите папку с документами — платформа сама разберётся, что из неё нужно загружать."
              action={
                <Link to="/tender/cases/new">
                  <Button variant="primary">Новая закупка</Button>
                </Link>
              }
            />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-xs text-ink-muted">
                  <th className="w-12 px-3 py-2.5 text-right font-medium">№</th>
                  <th className="px-5 py-2.5 font-medium">Закупка</th>
                  <th className="px-3 py-2.5 font-medium">Заказчик</th>
                  <th className="px-3 py-2.5 text-right font-medium">Файлов</th>
                  <th className="px-3 py-2.5 text-right font-medium">Объём</th>
                  <th className="px-5 py-2.5 font-medium">Состояние</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((item, position) => (
                  <tr
                    key={item.id}
                    className="border-b border-hairline last:border-0 hover:bg-plane"
                  >
                    <td className="px-3 py-3 text-right align-top tabular-nums text-ink-muted">
                      {position + 1}
                    </td>
                    <td className="px-5 py-3">
                      <Link
                        to={`/tender/cases/${item.id}`}
                        className="font-medium text-ink hover:text-series-1"
                      >
                        {item.title}
                      </Link>
                      {item.subject && (
                        <div className="mt-0.5 truncate text-xs text-ink-muted">
                          {item.subject}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-ink-secondary">
                      {item.customer || "—"}
                    </td>
                    <td className="px-3 py-3 text-right text-ink-secondary">
                      {item.files_count}
                    </td>
                    <td className="px-3 py-3 text-right text-ink-secondary">
                      {item.total_bytes ? bytes(item.total_bytes) : "—"}
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={STATUS[item.status].tone}>
                        {STATUS[item.status].title}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}
