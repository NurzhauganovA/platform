/**
 * Предложение разделить папку на закупки.
 *
 * Показывается там, где человек ищет позиции и видит ноль. Это не подсказка
 * «на будущее», а объяснение прямо на месте: позиций нет не потому, что
 * система не справилась, а потому что в папке лежат два десятка разных
 * закупок, и сводить их предложения в одну таблицу нечего.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { tender } from "@/api/tender";
import { Button, Card } from "@/ui";

function plural(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

export function SplitBanner({ caseId }: { caseId: string }) {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["split", caseId],
    queryFn: () => tender.splitPreview(caseId),
  });

  const split = useMutation({
    mutationFn: () => tender.split(caseId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["cases"] });
      navigate("/tender/cases");
    },
  });

  if (!data?.can_split) return null;
  const cases = data.cases;

  return (
    <Card className="border-series-1/40 bg-series-1/5">
      <div className="space-y-3 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink">
              В этой папке {cases.length} разных закупок
            </h3>
            <p className="mt-1 text-sm text-ink-secondary">
              Каждое заключение — про свой предмет: сравнивать их между собой нечего. Разделите
              папку, и каждая закупка станет отдельной карточкой со своими предложениями.
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="ghost" onClick={() => setOpen((value) => !value)}>
              {open ? "Свернуть" : "Показать список"}
            </Button>
            <Button
              variant="primary"
              onClick={() => split.mutate()}
              disabled={split.isPending}
            >
              {split.isPending ? "Делим…" : `Разделить на ${cases.length}`}
            </Button>
          </div>
        </div>

        {open && (
          <ol className="max-h-96 space-y-1 overflow-y-auto border-t border-series-1/20 pt-3">
            {cases.map((item, index) => (
              <li key={item.title + index} className="flex items-baseline gap-2.5 text-sm">
                <span className="w-6 shrink-0 text-right text-xs text-ink-muted">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink">{item.title}</span>
                <span className="shrink-0 text-xs text-ink-muted">
                  {item.files.length} {plural(item.files.length, "файл", "файла", "файлов")}
                  {item.anchors > 1 && ` · ${item.anchors} редакции`}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}
