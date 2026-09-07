/**
 * Взять лот в работу.
 *
 * Заводит карточку по строке рабочего списка и уводит на неё. Дальше лот живёт
 * там: статус, отделы, задачи, согласование.
 *
 * Снимок закупки уходит на сервер вместе с нажатием, а не подтягивается им из
 * базы площадки. Выгрузка пересобирает список каждый час, названия и суммы у
 * заказчика меняются, а карточка должна остаться той, по которой её завели.
 *
 * Уже заведённая карточка не заводится второй раз: кнопка превращается в
 * ссылку на неё. Два ответственных и два набора подписей по одному лоту хуже,
 * чем лишнее нажатие.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { cardsApi, type Card } from "@/api/cards";
import { Button } from "@/ui";

export function TakeToWork({
  module,
  rowId,
  code,
  sourceNumber,
  title,
  customer,
  amount,
  enstruCode,
  deadline,
}: {
  module: string;
  rowId: string;
  code: string;
  sourceNumber?: string;
  title: string;
  customer?: string;
  amount?: number | null;
  enstruCode?: string;
  deadline?: string | null;
}) {
  const navigate = useNavigate();

  // Ищем среди уже взятых. Отдельного эндпоинта «есть ли карточка» нет
  // намеренно: список взятых в работу и так лежит в кэше запросов — на него
  // смотрит соседний экран, — и второй запрос ради одной строки лишний.
  const { data: taken } = useQuery({
    queryKey: ["cards"],
    queryFn: () => cardsApi.list(),
    staleTime: 60_000,
  });
  const already: Card | undefined = taken?.find(
    (item) => item.module === module && item.row_id === rowId,
  );

  const take = useMutation({
    mutationFn: () =>
      cardsApi.open({
        module,
        row_id: rowId,
        code,
        source_number: sourceNumber,
        title,
        customer,
        amount,
        enstru_code: enstruCode,
        deadline,
      }),
    onSuccess: (card) => navigate(`/work/lots/${card.id}`),
  });

  // Уже взят — вместо «взять» дорога к карточке: сервер вторую по тому же
  // лоту не заведёт, а человек узнал бы об этом, уже нажав.
  if (already) {
    return (
      <Button
        variant="secondary"
        onClick={() => navigate(`/work/lots/${already.id}`)}
        title={`Лот в работе, ${already.status_name.toLowerCase()}. ${
          already.owner
            ? `Сейчас у ${already.owner}`
            : "Ответственный не назначен"
        }${already.open_tasks > 0 ? `, открытых задач ${already.open_tasks}` : ""}`}
      >
        В работе · {already.status_name}
      </Button>
    );
  }

  return (
    <>
      <Button
        variant="primary"
        disabled={take.isPending}
        onClick={() => take.mutate()}
        title="Заведём карточку лота: статус, ответственные, задачи отделов и согласование перед подачей"
      >
        {take.isPending ? "Заводим…" : "Взять в работу"}
      </Button>
      {take.error && (
        <p className="w-full text-sm text-critical">
          {take.error instanceof Error
            ? take.error.message
            : "Не получилось взять в работу"}
        </p>
      )}
    </>
  );
}
