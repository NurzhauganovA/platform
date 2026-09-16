/**
 * Число из ячейки цены — с арифметикой.
 *
 * Количество у позиций разное, и цену набирают по-разному: «18000» за штуку и
 * «2 * 18000», когда штук две. Считать произведение в уме и записывать итог
 * значит потерять ответ на вопрос «откуда эта сумма»: через неделю в ячейке
 * стоит 36000, а сколько там было штук и по какой цене — уже не спросишь.
 *
 * **Это не «умная ячейка Excel».** Ссылок на другие строки нет и не будет:
 * таблица разбора живёт копиями (снабжение получает свою), и ссылка,
 * пережившая копирование, указывала бы в чужую таблицу. Четыре действия и
 * скобки — ровно то, чем считают количество на цену.
 *
 * Разбор свой, а не `eval`. В ячейку попадает то, что набрал человек, и она
 * же приезжает с сервера — то есть из базы, куда её мог положить кто угодно с
 * доступом к разбору. `eval` в этом месте означает чужой код в чужой вкладке
 * с чужой сессией.
 *
 * Считается в браузере, и это не срез угла: сервер цену не читает и нигде не
 * складывает (`modules/sheets.py` только объявляет столбец), а итог наверху
 * должен меняться вместе с набором — не после сохранения. Появится сложение
 * на сервере — правило переедет туда целиком, а не удвоится.
 */

/** Что в ячейке: число, выражение или невнятица. */
export type Amount =
  | { kind: "number"; value: number }
  | { kind: "formula"; value: number }
  | { kind: "empty" }
  | { kind: "broken" };

/**
 * Разбирает ячейку.
 *
 * Возвращает не только число, но и то, как оно получено: ячейку с выражением
 * показывают иначе, чем ячейку с числом, а непонятную надо назвать вслух —
 * молча выпавшая из суммы строка расходится с тем, что видно глазами.
 */
export function parse(raw: string): Amount {
  const text = plain(raw).trim();
  if (!text) return { kind: "empty" };

  const tokens = scan(text);
  if (tokens === null) return { kind: "broken" };

  const reader = { tokens, at: 0 };
  const value = expression(reader);
  if (value === null || reader.at !== tokens.length) return { kind: "broken" };
  if (!Number.isFinite(value)) return { kind: "broken" };

  // Копейки: в тенге их почти не пишут, но «2 * 1250,50» обязано сойтись.
  const rounded = Math.round(value * 100) / 100;
  const bare = tokens.length === 1 && tokens[0].kind === "number";
  return { kind: bare ? "number" : "formula", value: rounded };
}

/**
 * Текст из ячейки: разметку убираем.
 *
 * Цену пишут тем же полем, что и остальное, — с цветом и ссылками, — и в
 * значении лежит разметка. Без этого «<span style="color:#c00">18000</span>»
 * разбирался бы как невнятица, то есть выпадал из итога ровно в той строке,
 * которую человек нарочно выделил как спорную.
 */
function plain(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/gi, "\u00a0")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">");
}

/** Число из ячейки или `null`. Для тех мест, где важен только итог. */
export function amount(raw: string): number | null {
  const found = parse(raw);
  return found.kind === "number" || found.kind === "formula"
    ? found.value
    : null;
}

/**
 * Сумма ячеек — в тиынах, а потом обратно.
 *
 * Складывать доли рубля в двоичной дроби нельзя: 0.1 + 0.2 даёт
 * 0.30000000000000004, и на сорока строках итог разъезжается с тем, что
 * человек сложит на калькуляторе. В целых копейках этого не бывает.
 */
export function total(values: number[]): number {
  return values.reduce((sum, one) => sum + Math.round(one * 100), 0) / 100;
}

/** Сумма словами: «36 000 ₸». Разряды неразрывным пробелом — иначе число
 *  переносится по строке пополам. */
export function money(value: number): string {
  const whole = Number.isInteger(value);
  return `${value.toLocaleString("ru-RU", {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  })} ₸`;
}

// --- разбор ---------------------------------------------------------------

type Token =
  | { kind: "number"; value: number }
  | { kind: "op"; value: "+" | "-" | "*" | "/" }
  | { kind: "open" }
  | { kind: "close" };

/**
 * Знаки умножения, которые набирают люди.
 *
 * Русская «х» здесь не прихоть: она стоит на той же клавише, что латинская, и
 * в русской раскладке «2 х 18000» набирается само собой. Отвергать её значит
 * показывать «не считается» на том, что человек считает написанным верно.
 */
const TIMES = new Set(["*", "x", "X", "х", "Х", "×", "•"]);

const DIVIDE = new Set(["/", ":", "÷"]);

/** Разбивает текст на числа, знаки и скобки. `null` — встретилось лишнее. */
function scan(text: string): Token[] | null {
  const tokens: Token[] = [];
  // Пробел неразрывный — из вставки из Excel; знак валюты и «тг» дописывают
  // руками. Ни то, ни другое на смысл не влияет.
  const clean = text
    .replace(/ /g, " ")
    .replace(/₸|тенге|тг\.?/gi, " ")
    // Знак равенства в начале — привычка из Excel. Просьба посчитать, а не
    // ошибка: человек написал ровно то, что имел в виду.
    .replace(/^\s*=/, " ");

  let at = 0;
  while (at < clean.length) {
    const char = clean[at];
    if (char === " " || char === "\t") {
      at += 1;
      continue;
    }
    if (char === "(") {
      tokens.push({ kind: "open" });
      at += 1;
      continue;
    }
    if (char === ")") {
      tokens.push({ kind: "close" });
      at += 1;
      continue;
    }
    if (char === "+" || char === "-" || char === "−") {
      tokens.push({ kind: "op", value: char === "−" ? "-" : char });
      at += 1;
      continue;
    }
    if (TIMES.has(char)) {
      tokens.push({ kind: "op", value: "*" });
      at += 1;
      continue;
    }
    if (DIVIDE.has(char)) {
      tokens.push({ kind: "op", value: "/" });
      at += 1;
      continue;
    }
    if (!/[\d,.]/.test(char)) return null;

    const read = number(clean, at);
    if (read === null) return null;
    tokens.push({ kind: "number", value: read.value });
    at = read.at;
  }
  return tokens.length ? tokens : null;
}

/**
 * Число с того места, где стоим.
 *
 * Пробел внутри числа — разделитель разрядов: «1 250 000» люди пишут именно
 * так, и вставка из Excel приходит в том же виде. Поэтому пробел съедается
 * только между цифрами: в «2 * 18000» за пробелом стоит знак, а не цифра, и
 * число на нём кончается.
 */
function number(
  text: string,
  from: number,
): { value: number; at: number } | null {
  let at = from;
  let digits = "";
  let dot = false;

  while (at < text.length) {
    const char = text[at];
    if (/\d/.test(char)) {
      digits += char;
      at += 1;
      continue;
    }
    if ((char === "," || char === ".") && !dot) {
      // Разделителем дробной части считаем и запятую, и точку: в книге
      // встречаются обе, а разряды у нас отделяют пробелом.
      dot = true;
      digits += ".";
      at += 1;
      continue;
    }
    if (char === " " && /\d/.test(text[at + 1] ?? "") && !dot) {
      at += 1;
      continue;
    }
    break;
  }

  if (!digits || digits === ".") return null;
  const value = Number(digits);
  return Number.isFinite(value) ? { value, at } : null;
}

type Reader = { tokens: Token[]; at: number };

/** сложение и вычитание */
function expression(reader: Reader): number | null {
  let left = term(reader);
  if (left === null) return null;
  for (;;) {
    const token = reader.tokens[reader.at];
    if (token?.kind !== "op" || (token.value !== "+" && token.value !== "-"))
      return left;
    reader.at += 1;
    const right = term(reader);
    if (right === null) return null;
    left = token.value === "+" ? left + right : left - right;
  }
}

/** умножение и деление */
function term(reader: Reader): number | null {
  let left = unary(reader);
  if (left === null) return null;
  for (;;) {
    const token = reader.tokens[reader.at];
    if (token?.kind !== "op" || (token.value !== "*" && token.value !== "/"))
      return left;
    reader.at += 1;
    const right = unary(reader);
    if (right === null) return null;
    // Деление на ноль даёт бесконечность, а не ошибку: без этой проверки в
    // итог уехало бы «∞ ₸».
    if (token.value === "/" && right === 0) return null;
    left = token.value === "*" ? left * right : left / right;
  }
}

/** знак перед числом */
function unary(reader: Reader): number | null {
  const token = reader.tokens[reader.at];
  if (token?.kind === "op" && (token.value === "-" || token.value === "+")) {
    reader.at += 1;
    const value = unary(reader);
    return value === null ? null : token.value === "-" ? -value : value;
  }
  return atom(reader);
}

/** число или выражение в скобках */
function atom(reader: Reader): number | null {
  const token = reader.tokens[reader.at];
  if (token === undefined) return null;
  if (token.kind === "number") {
    reader.at += 1;
    return token.value;
  }
  if (token.kind === "open") {
    reader.at += 1;
    const value = expression(reader);
    if (value === null) return null;
    if (reader.tokens[reader.at]?.kind !== "close") return null;
    reader.at += 1;
    return value;
  }
  return null;
}
