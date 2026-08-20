/**
 * Как показываются значения.
 *
 * Одно место на таблицу и на разбор: формат приходит с сервера тот же самый
 * (он взят у колонки книги), и раскрашивать его двумя способами значит
 * однажды показать «−98,800» в списке и «−98,8» в разборе.
 */

import type { CellFormat } from "@/api/worklist";
import { money } from "@/ui";

/** «13.08.2026 09:00» — как в книге, в местном времени сотрудника. */
export function formatDate(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  // Без запятой между датой и временем: в книге формат «DD.MM.YYYY HH:MM».
  return parsed
    .toLocaleString("ru-KZ", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
    .replace(",", "");
}

export function formatValue(
  value: { text: string; number: number | null },
  format: CellFormat = "text",
): string {
  if (format === "datetime" && value.text) return formatDate(value.text);
  if (value.number == null) return value.text;

  switch (format) {
    case "money":
      return money(value.number);
    case "percent":
      // Доля приходит как 0.24 — в книге у этой колонки формат «0.0%».
      return `${(value.number * 100).toFixed(1)}%`;
    case "quantity":
      // Формат книги «#,##0.###»: до трёх знаков, хвостовые нули отброшены.
      // Иначе «−98,8 часа» превращается в «−98,800» и читается как
      // девяносто восемь тысяч.
      return value.number.toLocaleString("ru-KZ", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 3,
      });
    default:
      return money(value.number);
  }
}

/**
 * Сколько часов осталось до срока и надо ли это подсвечивать.
 *
 * Цвет здесь не единственный признак: рядом всегда стоит слово — «истёк»,
 * «сегодня». Без него красная дата ничем не отличалась бы от обычной.
 */
export function urgency(
  iso: string | null,
): { text: string; className: string } | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;

  const hours = (at.getTime() - Date.now()) / 3_600_000;
  if (hours < 0) return { text: "истёк", className: "text-critical" };
  if (hours < 24) return { text: "сегодня", className: "text-warning" };
  return null;
}
