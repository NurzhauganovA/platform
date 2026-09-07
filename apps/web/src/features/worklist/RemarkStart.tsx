/**
 * Завести обсуждение с карточки лота.
 *
 * Кнопка, а не блок с заголовком и абзацем пояснения. Блоком её не видели:
 * рамка в цвет разделителя посреди других таких же рамок читается как ещё
 * один раздел разбора, и нажимать её никто не пробовал. Что будет после
 * нажатия — в подсказке при наведении, а не строкой под словом.
 *
 * Заводит и сразу ставит написание в очередь. Разделять незачем: пустое
 * обсуждение без текста никому не нужно, а лишнее нажатие на срочной работе —
 * лишняя минута.
 *
 * Повторное нажатие безопасно: обсуждение по лоту одно, сервер вернёт то же.
 * Поэтому кнопка не запирается навсегда — модель могла и не справиться, и
 * перезапуск должен быть под рукой.
 */

import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { remarks } from "@/api/remarks";
import { Button } from "@/ui";

export function RemarkStart({ lotNumber }: { lotNumber: string }) {
  const navigate = useNavigate();
  const start = useMutation({
    mutationFn: () => remarks.start(lotNumber),
    onSuccess: (started) => navigate(`/goszakup/remarks/${started.remark_id}`),
  });

  return (
    <>
      <Button
        variant="accent"
        disabled={start.isPending}
        onClick={() => start.mutate()}
        title="Модель разберёт спецификацию и укажет, что в ней ограничивает конкуренцию. Перед отправкой текст читает человек"
      >
        {start.isPending ? "Заводим…" : "Обсуждение"}
      </Button>
      {start.error && (
        <p className="w-full text-sm text-critical">
          {start.error instanceof Error
            ? start.error.message
            : "Не получилось завести обсуждение"}
        </p>
      )}
    </>
  );
}
