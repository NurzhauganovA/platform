/**
 * Действия по закупке: поиск на рынках и сборка нашего предложения.
 *
 * Порядок здесь не произволен и виден человеку. Разбор отвечает, что написано
 * в бумагах. Решение — стоит ли участвовать. Поиск даёт нашу собственную цену,
 * ту, по которой мы можем купить; до него маржа остаётся догадкой. И только
 * потом собирается КП.
 *
 * Рядом с каждой платной кнопкой сказано, что она стоит денег: разбор идёт
 * минутами, поиск ходит в интернет, а решение потратить — не то, что нажимают
 * мимоходом.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tender, type CaseStatus } from "@/api/tender";
import { Badge, Button, Card, Spinner, bytes, cx } from "@/ui";

export function Actions({
  caseId,
  status,
  onJob,
  busy,
}: {
  caseId: string;
  status: CaseStatus;
  onJob: (jobId: string) => void;
  busy: boolean;
}) {
  const client = useQueryClient();
  const analyzed = status === "analyzed";

  const { data: companies = [] } = useQuery({
    queryKey: ["companies"],
    queryFn: tender.companies,
    staleTime: 60 * 60 * 1000,
  });

  const [chosen, setChosen] = useState<string[]>([]);
  const [number, setNumber] = useState("");

  const { data: documents = [], refetch } = useQuery({
    queryKey: ["case-documents", caseId],
    queryFn: () => tender.documents(caseId),
  });

  const sourcing = useMutation({
    mutationFn: () => tender.sourcing(caseId),
    onSuccess: (started) => {
      onJob(started.job_id);
      client.invalidateQueries({ queryKey: ["comparison", caseId] });
    },
  });

  const offer = useMutation({
    mutationFn: () =>
      tender.offer(caseId, {
        companies: chosen.length ? chosen : companies.filter((c) => c.is_default).map((c) => c.key),
        number: number.trim() || null,
      }),
    onSuccess: (started) => {
      onJob(started.job_id);
      setTimeout(() => refetch(), 2500);
    },
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Поиск на рынках">
        <div className="space-y-3 px-5 py-4">
          <p className="text-sm text-ink-secondary">
            Ищет позиции закупки в Казахстане, Кыргызстане, России, Китае и Узбекистане и считает,
            где мы заработаем. Здесь впервые появляется наша собственная цена — та, по которой мы
            можем купить.
          </p>
          <div className="flex items-center gap-2">
            <Button
              onClick={() => sourcing.mutate()}
              disabled={busy || !analyzed || sourcing.isPending}
            >
              Искать
            </Button>
            <Badge tone="warning">платно — запросы идут в интернет</Badge>
          </div>
          {!analyzed && (
            <p className="text-xs text-ink-muted">Сначала разберите документы закупки.</p>
          )}
        </div>
      </Card>

      <Card title="Наше предложение">
        <div className="space-y-3 px-5 py-4">
          <p className="text-sm text-ink-secondary">
            Собирает КП для заказчика и задание закупщику. Денег не стоит: цена считается кодом по
            уже известным величинам.
          </p>

          <fieldset>
            <legend className="mb-1.5 text-xs font-medium text-ink-muted">От кого отправляем</legend>
            <div className="flex flex-wrap gap-1.5">
              {companies.map((company) => {
                const active = chosen.includes(company.key) || (!chosen.length && company.is_default);
                return (
                  <button
                    key={company.key}
                    type="button"
                    onClick={() =>
                      setChosen((current) =>
                        current.includes(company.key)
                          ? current.filter((key) => key !== company.key)
                          : [...current, company.key],
                      )
                    }
                    title={company.missing.length ? `Не заполнено: ${company.missing.join(", ")}` : ""}
                    className={cx(
                      "rounded-full border px-3 py-1 text-xs transition",
                      active
                        ? "border-series-1 bg-series-1/10 font-medium text-series-1"
                        : "border-baseline text-ink-secondary hover:bg-plane",
                    )}
                  >
                    {company.name}
                    {company.missing.length > 0 && (
                      // Незаполненный реквизит должен всплыть при выборе,
                      // а не в готовом КП у заказчика.
                      <span aria-label="есть незаполненные реквизиты" className="ml-1 text-warning">
                        ▲
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <div className="flex items-end gap-2">
            <label className="flex-1">
              <span className="mb-1 block text-xs font-medium text-ink-muted">Исходящий номер</span>
              <input
                value={number}
                onChange={(event) => setNumber(event.target.value)}
                placeholder="7"
                className="w-full rounded-[8px] border border-baseline bg-surface px-3 py-1.5 text-sm text-ink"
              />
            </label>
            <Button
              variant="primary"
              onClick={() => offer.mutate()}
              disabled={busy || !analyzed || offer.isPending}
            >
              Собрать КП
            </Button>
          </div>

          {offer.isPending && <Spinner label="Собираем документы…" />}

          {documents.length > 0 && (
            <ul className="space-y-1 border-t border-hairline pt-3">
              {documents.map((document) => (
                <li key={document.name} className="flex items-center justify-between gap-3">
                  <a
                    href={`/api/tender/cases/${caseId}/documents/${encodeURIComponent(document.name)}`}
                    download
                    className="min-w-0 truncate text-sm text-series-1 hover:underline"
                  >
                    {document.name}
                  </a>
                  <span className="shrink-0 text-xs text-ink-muted">
                    {bytes(document.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
