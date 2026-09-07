/**
 * Выборка закупки с портала по номеру — мимо списка кодов ЕНС ТРУ.
 *
 * Обход идёт строго по номенклатуре, и это правильно: на портале сотни тысяч
 * лотов, и без списка раздел был бы чужой лентой. Но код закупке ставит
 * заказчик, а не мы: моноблоки уходят в «прочее», серверы в «оборудование».
 * Такая закупка не появляется нигде, и узнают о ней из письма — с номером на
 * руках и с приёмом, который кончается послезавтра.
 *
 * Номер лота и номер объявления человек различает не всегда: в письме стоит то
 * одно, то другое, а выглядят они одинаково. Поле одно, разбирается сервер —
 * сперва лот, потом объявление.
 *
 * Найденное сразу берётся в работу и появляется в этом же списке. Отправлять
 * человека после выборки в соседний раздел за второй кнопкой значит делить
 * одно действие надвое: закупку уже пропустили, её ищут не из любопытства.
 *
 * Ход прогона виден строкой: портал отвечает секунду в тихий час и полторы
 * минуты в неудачный, и кнопка без ответа выглядит непрожатой.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import { goszakup, type Fetched } from "@/api/goszakup";
import { ApiError } from "@/api/client";
import { useJobStream } from "@/api/jobs";
import { Button, Input, Spinner, cx } from "@/ui";

export function FetchByNumber() {
  const cache = useQueryClient();
  const [number, setNumber] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [trouble, setTrouble] = useState("");
  const [done, setDone] = useState<Fetched | null>(null);

  const run = useJobStream(jobId, () => {
    // Список карточек перечитываем: найденное уже взято в работу и должно
    // появиться здесь же, без перезагрузки страницы.
    void cache.invalidateQueries({ queryKey: ["cards"] });
  });
  const going =
    run === null ? jobId !== null : ["queued", "running"].includes(run.status);

  // Итог снимается с прогона, а не запрашивается отдельно: он уже пришёл в
  // последнем событии потока.
  if (run?.status === "succeeded" && run.result && !done) {
    setDone(run.result as unknown as Fetched);
    setNumber("");
  }

  const start = useMutation({
    mutationFn: () => goszakup.fetch(number),
    onSuccess: (started) => {
      setTrouble("");
      setDone(null);
      setJobId(started.job_id);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const ready = number.trim().length > 2 && !going && !start.isPending;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Input
          value={number}
          onChange={(event) => setNumber(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && ready) start.mutate();
          }}
          placeholder="Номер лота или объявления"
          title="Например 87164506-ОИ2 или 17561972-1. Ищем строго по нему, список кодов ЕНС ТРУ не участвует"
          className="w-56"
        />
        <Button
          variant="secondary"
          onClick={() => start.mutate()}
          disabled={!ready}
        >
          {going || start.isPending ? "Ищем…" : "Найти на портале"}
        </Button>
      </div>

      {going && (
        <div className="flex items-center gap-2">
          <Spinner label={run?.note || "Ставим в очередь…"} />
        </div>
      )}

      {run?.status === "failed" && (
        <p className="text-xs text-critical">✕ Не получилось. {run.error}</p>
      )}

      {/* Ничего не найдено — это ответ, а не сбой: номер набирают с опечаткой,
          а объявления снимают. Красный крест отправил бы человека искать
          поломку у нас вместо того, чтобы перечитать номер в письме. */}
      {done && !going && (
        <p
          className={cx(
            "text-xs",
            done.found === 0 ? "text-ink-muted" : "text-good",
          )}
        >
          {done.found === 0
            ? `Портал не знает закупки «${done.number}». Проверьте номер: он есть в письме и в карточке на портале.`
            : `Нашли ${done.found} и взяли в работу: ${done.codes.join(", ")}`}
        </p>
      )}

      {trouble && <p className="text-xs text-critical">{trouble}</p>}
    </div>
  );
}
