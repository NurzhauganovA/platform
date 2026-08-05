/**
 * Новая закупка: выбор папки и загрузка.
 *
 * Порядок шагов повторяет то, как это происходит на самом деле. Человек
 * выбирает папку — ту же, что лежит у него на диске. Браузер считает хэши, не
 * отправляя файлы. Платформа отвечает, что из этого нужно грузить. И только
 * потом идёт передача.
 *
 * План показывается до загрузки намеренно: на архиве в два гигабайта разница
 * между «грузить всё» и «грузить один файл» — это часы. И там же видно, за что
 * платить не придётся: содержимое, которое ядро уже разбирало.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { tender, type UploadPlan } from "@/api/tender";
import { PageHeader } from "@/shell/AppShell";
import { Badge, Button, Card, Field, Input, Progress, Spinner, StatTile, bytes, cx } from "@/ui";
import { folderNameOf, planUpload, prepare, upload, type PickedFile } from "./upload";

type Step = "pick" | "hashing" | "plan" | "uploading" | "done";

export function NewCasePage() {
  const [step, setStep] = useState<Step>("pick");
  const [title, setTitle] = useState("");
  const [customer, setCustomer] = useState("");
  const [picked, setPicked] = useState<PickedFile[]>([]);
  const [plan, setPlan] = useState<UploadPlan | null>(null);
  const [progress, setProgress] = useState({ done: 0, total: 0, note: "" });
  const [error, setError] = useState<string | null>(null);

  const navigate = useNavigate();
  const client = useQueryClient();

  async function onFolder(fileList: FileList | null) {
    if (!fileList?.length) return;
    setError(null);
    const files = Array.from(fileList);
    setTitle((current) => current || folderNameOf(files));
    setStep("hashing");

    try {
      const prepared = await prepare(files, (done, total) =>
        setProgress({ done, total, note: "считаем содержимое" }),
      );
      setPicked(prepared);
      setPlan(await planUpload(prepared));
      setStep("plan");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось прочитать папку");
      setStep("pick");
    }
  }

  async function onUpload() {
    if (!plan || !title.trim()) return;
    setError(null);
    setStep("uploading");

    try {
      const created = await tender.createCase({ title: title.trim(), customer: customer.trim() });
      const attached = await upload(picked, plan, (done, total, note) =>
        setProgress({ done, total, note }),
      );
      await tender.attachFiles(created.id, attached);
      await client.invalidateQueries({ queryKey: ["cases"] });
      setStep("done");
      navigate(`/tender/cases/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Загрузка не удалась");
      setStep("plan");
    }
  }

  return (
    <>
      <PageHeader title="Новая закупка" subtitle="Выберите папку с документами закупки" />

      <div className="max-w-4xl space-y-4 px-8 py-6">
        {error && (
          <Card className="border-critical/40 bg-critical/10 px-5 py-3">
            <p className="text-sm text-critical">{error}</p>
          </Card>
        )}

        <Card title="Папка">
          <div className="space-y-4 px-5 py-5">
            <label
              className={cx(
                "flex cursor-pointer flex-col items-center justify-center gap-2",
                "rounded-[10px] border-2 border-dashed border-baseline px-6 py-10",
                "transition hover:border-series-1 hover:bg-series-1/5",
              )}
            >
              <input
                type="file"
                className="sr-only"
                // Выбор папки целиком: подпапки сохраняются, и «обновленные кп»
                // остаётся отдельной папкой — по ней ядро отличает состав закупок.
                {...{ webkitdirectory: "", directory: "" }}
                multiple
                onChange={(event) => onFolder(event.target.files)}
              />
              <span className="text-sm font-medium text-ink">Выбрать папку закупки</span>
              <span className="text-xs text-ink-muted">
                Файлы остаются у вас, пока не станет ясно, что из них нужно
              </span>
            </label>

            {step === "hashing" && (
              <div className="space-y-2">
                <Spinner label={`Читаем файлы: ${progress.done} из ${progress.total}`} />
                <Progress percent={(progress.done / Math.max(1, progress.total)) * 100} />
              </div>
            )}
          </div>
        </Card>

        {plan && step !== "hashing" && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatTile label="Всего файлов" value={plan.total} />
              <StatTile
                label="Загрузить"
                value={plan.to_upload}
                hint={plan.upload_bytes ? bytes(plan.upload_bytes) : "ничего"}
                tone="series-1"
              />
              <StatTile
                label="Уже загружено"
                value={plan.skipped_known}
                hint="передавать не нужно"
                tone="series-3"
              />
              <StatTile
                label="Разбор оплачен"
                value={plan.already_analyzed}
                hint="не будет стоить денег"
                tone="good"
              />
            </div>

            <Card title="Что попадёт в закупку">
              <ul className="max-h-72 divide-y divide-hairline overflow-y-auto">
                {plan.files.map((file) => (
                  <li
                    key={file.relative_path}
                    className="flex items-center justify-between gap-3 px-5 py-2 text-sm"
                  >
                    <span
                      className={cx(
                        "min-w-0 truncate",
                        file.supported ? "text-ink" : "text-ink-muted line-through",
                      )}
                      title={file.relative_path}
                    >
                      {file.relative_path}
                    </span>
                    {!file.supported ? (
                      <Badge tone="neutral">не читается</Badge>
                    ) : file.known ? (
                      <Badge tone="info">уже загружен</Badge>
                    ) : file.analysis_cached ? (
                      <Badge tone="good">разбор оплачен</Badge>
                    ) : (
                      <Badge tone="neutral">загрузим</Badge>
                    )}
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Как назвать закупку">
              <div className="grid gap-4 px-5 py-5 sm:grid-cols-2">
                <Field label="Название" hint="По умолчанию — имя выбранной папки">
                  <Input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="Системный блок от 27.07.2027 г"
                  />
                </Field>
                <Field label="Заказчик" hint="Необязательно">
                  <Input
                    value={customer}
                    onChange={(event) => setCustomer(event.target.value)}
                    placeholder="ТОО «Каратау»"
                  />
                </Field>
              </div>
            </Card>

            <div className="flex items-center justify-between gap-4">
              {step === "uploading" ? (
                <div className="min-w-0 flex-1 space-y-2">
                  <Spinner
                    label={`Передаём: ${progress.done} из ${progress.total}${
                      progress.note ? ` — ${progress.note}` : ""
                    }`}
                  />
                  <Progress percent={(progress.done / Math.max(1, progress.total)) * 100} />
                </div>
              ) : (
                <p className="text-sm text-ink-muted">
                  {plan.to_upload
                    ? `Будет передано ${bytes(plan.upload_bytes)}`
                    : "Передавать нечего — всё уже загружено"}
                </p>
              )}

              <Button
                variant="primary"
                onClick={onUpload}
                disabled={step === "uploading" || !title.trim() || !plan.files.length}
              >
                Создать закупку
              </Button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
