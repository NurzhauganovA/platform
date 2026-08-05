/**
 * Карточка закупки.
 *
 * Здесь запускается платный разбор, поэтому кнопка не одинока: рядом видно,
 * сколько файлов, сколько из них уже разобрано и что разбор идёт минутами.
 * Прогресс приходит потоком событий — за минуты связь рвётся, и браузер
 * восстанавливает поток сам.
 */

import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { jobs, tender, type Job } from "@/api/tender";
import { PageHeader } from "@/shell/AppShell";
import { Badge, Button, Card, Progress, Spinner, StatTile, bytes, cx } from "@/ui";
import { Comparison } from "./Comparison";

/** Подписка на живой прогресс задачи. */
function useJobStream(jobId: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const client = useQueryClient();
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const source = new EventSource(`/api/jobs/${jobId}/stream`, { withCredentials: true });

    source.onmessage = (event) => {
      const data = JSON.parse(event.data) as Partial<Job>;
      setJob((current) => ({ ...(current ?? ({ id: jobId } as Job)), ...data }) as Job);

      if (data.status && ["succeeded", "failed", "cancelled"].includes(data.status)) {
        source.close();
        // Разбор закончился — карточка и список должны показать новое состояние.
        if (seen.current !== data.status) {
          seen.current = data.status;
          client.invalidateQueries({ queryKey: ["case"] });
          client.invalidateQueries({ queryKey: ["cases"] });
          client.invalidateQueries({ queryKey: ["job", jobId] });
        }
      }
    };
    source.onerror = () => source.close();
    return () => source.close();
  }, [jobId, client]);

  return job;
}

type Tab = "comparison" | "documents";

export function CasePage() {
  const { caseId = "" } = useParams();
  const [jobId, setJobId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("comparison");
  const client = useQueryClient();

  const { data: item, isLoading } = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => tender.case(caseId),
    enabled: Boolean(caseId),
  });

  const { data: recent } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => jobs.get(jobId as string),
    enabled: Boolean(jobId),
  });

  const live = useJobStream(jobId);
  const job = live ?? recent ?? null;
  const running = job?.status === "queued" || job?.status === "running";

  const analyze = useMutation({
    mutationFn: () => tender.analyze(caseId),
    onSuccess: (started) => {
      setJobId(started.job_id);
      client.invalidateQueries({ queryKey: ["case", caseId] });
    },
  });

  if (isLoading || !item) {
    return (
      <div className="px-8 py-8">
        <Spinner label="Открываем закупку…" />
      </div>
    );
  }

  const result = (job?.result ?? {}) as Record<string, number>;

  return (
    <>
      <PageHeader
        title={item.title}
        subtitle={[item.customer, item.subject].filter(Boolean).join(" · ") || undefined}
        action={
          <div className="flex items-center gap-2">
            <Link to="/tender/cases">
              <Button variant="ghost">К списку</Button>
            </Link>
            <Button
              variant="primary"
              onClick={() => analyze.mutate()}
              disabled={running || analyze.isPending || !item.files.length}
            >
              {running ? "Разбираем…" : "Разобрать"}
            </Button>
          </div>
        }
      />

      <div className="space-y-4 px-8 py-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Документов" value={item.files.length} />
          <StatTile label="Объём" value={bytes(item.total_bytes)} />
          <StatTile
            label="Разобрано"
            value={result.documents ?? (item.status === "analyzed" ? item.files.length : 0)}
            tone="series-3"
          />
          <StatTile
            label="Распознано страниц"
            value={result.ocr_pages ?? 0}
            hint="сканы, прошедшие через модель"
            tone="series-2"
          />
        </div>

        {job && (
          <Card
            title="Разбор"
            action={
              <Badge
                tone={
                  job.status === "succeeded"
                    ? "good"
                    : job.status === "failed"
                      ? "critical"
                      : job.status === "cancelled"
                        ? "neutral"
                        : "warning"
                }
              >
                {
                  {
                    queued: "в очереди",
                    running: "идёт",
                    succeeded: "готово",
                    failed: "ошибка",
                    cancelled: "отменён",
                  }[job.status]
                }
              </Badge>
            }
          >
            <div className="space-y-3 px-5 py-4">
              <div className="flex items-baseline justify-between gap-4 text-sm">
                <span className="min-w-0 truncate text-ink-secondary">{job.note || "…"}</span>
                <span className="shrink-0 font-medium text-ink">{job.percent}%</span>
              </div>
              <Progress
                percent={job.percent}
                tone={job.status === "failed" ? "critical" : "series-1"}
              />

              {job.error && (
                <p className="rounded-[8px] border border-critical/40 bg-critical/10 px-3 py-2 text-sm text-critical">
                  {job.error}
                </p>
              )}

              {job.status === "succeeded" && (
                <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-secondary">
                  {Object.entries(result).map(([key, value]) => (
                    <div key={key} className="flex gap-1.5">
                      <dt className="text-ink-muted">{FIELD_TITLES[key] ?? key}:</dt>
                      <dd className="text-ink">{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </Card>
        )}

        <div className="flex gap-1 border-b border-hairline">
          {(
            [
              ["comparison", "Сравнение предложений"],
              ["documents", `Документы (${item.files.length})`],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cx(
                "-mb-px border-b-2 px-3 py-2 text-sm transition",
                tab === key
                  ? "border-series-1 font-medium text-series-1"
                  : "border-transparent text-ink-secondary hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "comparison" && <Comparison caseId={caseId} />}

        {tab === "documents" && (
        <Card title={`Документы (${item.files.length})`}>
          <ul className="divide-y divide-hairline">
            {item.files.map((file) => (
              <li
                key={file.id}
                className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm"
              >
                <span className="min-w-0 truncate text-ink" title={file.relative_path}>
                  {file.relative_path.includes("/") ? (
                    <>
                      <span className="text-ink-muted">
                        {file.relative_path.slice(0, file.relative_path.lastIndexOf("/") + 1)}
                      </span>
                      {file.relative_path.slice(file.relative_path.lastIndexOf("/") + 1)}
                    </>
                  ) : (
                    file.relative_path
                  )}
                </span>
                <span className={cx("shrink-0 text-xs text-ink-muted")}>
                  {bytes(file.size_bytes)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
        )}
      </div>
    </>
  );
}

const FIELD_TITLES: Record<string, string> = {
  files: "файлов",
  documents: "разобрано",
  pages: "страниц",
  ocr_pages: "распознано",
  failed: "с ошибкой",
  input_tokens: "токенов на вход",
  output_tokens: "токенов на выход",
};
