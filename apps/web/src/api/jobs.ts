/**
 * Живой ход фоновой задачи.
 *
 * Задачи в платформе идут минутами: обход портала, сборка книги, разбор
 * спецификации моделью. Опрашивать их запросом раз в секунду — это сотня
 * запросов на прогон и полоса, которая дёргается; сервер отдаёт поток
 * событий, и берём его.
 *
 * Общий для всех экранов. Пока хук жил внутри рабочего списка, второй экран,
 * которому понадобился прогресс, начал бы со своей копии — и разошёлся бы с
 * первой на первой же правке протокола событий.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "@/api/client";

export type JobRun = {
  id: string;
  kind: string;
  /**
   * Где задача сейчас.
   *
   * `lost` ставит браузер, а не сервер: поток оборвался или такой задачи уже
   * нет. Отдельным состоянием, потому что оно означает не «идёт» и не
   * «сделано», а «мы больше не знаем» — и вести себя по нему надо как по
   * законченной: перечитать результат и убрать полосу.
   */
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "lost";
  note: string;
  percent: number;
  error: string;
  result?: Record<string, unknown> | null;
};

const OVER = ["succeeded", "failed", "cancelled", "lost"];

/**
 * Подписывается на поток задачи и возвращает её состояние.
 *
 * Тип уточняется вызывающим: рабочему списку от задачи нужны ещё стоимость и
 * счётчики, карточке — только ход. Один общий тип пришлось бы расширять под
 * каждый экран, и он собрал бы поля, которых на этом экране не бывает.
 *
 * `onDone` зовётся один раз, когда задача кончилась, — по нему экран
 * перечитывает результат. Связь за минуты рвётся, и поток восстанавливается
 * сам; двойного вызова не будет, состояние окончания запоминается.
 */
export function useJobStream<T extends JobRun = JobRun>(
  jobId: string | null,
  onDone: () => void,
): T | null {
  const [job, setJob] = useState<T | null>(null);
  const finished = useRef<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setJob(null);
    finished.current = null;

    const source = new EventSource(`/api/jobs/${jobId}/stream`, {
      withCredentials: true,
    });
    source.onmessage = (event) => {
      const data = JSON.parse(event.data) as Partial<T>;
      setJob(
        (current) => ({ ...(current ?? ({ id: jobId } as T)), ...data }) as T,
      );

      if (data.status && OVER.includes(data.status)) {
        source.close();
        if (finished.current !== data.status) {
          finished.current = data.status;
          onDone();
        }
      }
    };
    source.onerror = () => {
      // Поток оборвался или такой задачи уже нет. Молчание здесь читалось
      // как «идёт»: полоса «Ставим в очередь…» висела до перезагрузки
      // страницы, хотя разбор давно закончился — а бывало, что и закончился
      // до того, как её открыли.
      source.close();
      setJob((current) => {
        if (current) return current;
        if (finished.current === null) {
          finished.current = "lost";
          onDone();
        }
        return { id: jobId, status: "lost", percent: 0 } as T;
      });
    };
    return () => source.close();
    // `onDone` намеренно не в зависимостях: он пересоздаётся на каждом
    // рендере, и поток пересоздавался бы вместе с ним — прогресс мигал бы.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return job;
}

/** Отменить прогон. Исполнитель увидит это между шагами и остановится. */
export const jobsApi = {
  cancel: (id: string) => api.post<JobRun>(`/api/jobs/${id}/cancel`),
};
