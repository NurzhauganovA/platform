/**
 * Ширина панели разбора: тянется мышью, помнится между открытиями.
 *
 * Разбор открывают десятки раз за час, и ширина — это личная настройка, как
 * размер окна. Сбрасывать её на каждое открытие значит заставлять тянуть
 * заново; поэтому она лежит в `localStorage`, а не в состоянии компонента.
 *
 * Границы жёсткие с обеих сторон. Снизу — чтобы панель не сжали до полосы, в
 * которой подпись поля и значение перестают помещаться в строку и таблица
 * конкурентов уезжает в горизонтальную прокрутку. Сверху — чтобы за ней
 * оставался виден список: разбор читают, сверяясь со строкой, из которой его
 * открыли, и панель во весь экран превращает панель обратно в страницу.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const KEY = "worklist:detail-width";

/** Меньше этого подписи полей начинают переноситься по слогам. */
export const MIN_WIDTH = 672;

/** Сколько экрана оставляем списку: без него теряется, откуда пришли. */
const KEEP_VISIBLE = 360;

/** Шире этого читать неудобно: строка в тысячу точек рвёт взгляд на возврате. */
const HARD_MAX = 1400;

export function maxWidth(viewport: number): number {
  // Не меньше минимума даже на узком экране: иначе границы схлопываются и
  // ручка перестаёт что-либо делать, оставаясь на виду.
  return Math.max(MIN_WIDTH, Math.min(HARD_MAX, viewport - KEEP_VISIBLE));
}

function clamp(value: number, viewport: number): number {
  return Math.min(Math.max(value, MIN_WIDTH), maxWidth(viewport));
}

function stored(): number | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    const value = raw ? Number(raw) : NaN;
    return Number.isFinite(value) ? value : null;
  } catch {
    // Приватный режим и запрет хранилища — не повод не открывать разбор.
    return null;
  }
}

export function usePanelWidth() {
  const [width, setWidth] = useState(() =>
    clamp(stored() ?? MIN_WIDTH, window.innerWidth),
  );
  const [dragging, setDragging] = useState(false);
  const start = useRef({ x: 0, width: 0 });

  const apply = useCallback((next: number) => {
    const value = clamp(next, window.innerWidth);
    setWidth(value);
    try {
      window.localStorage.setItem(KEY, String(value));
    } catch {
      // Не сохранилось — панель всё равно работает, просто забудет ширину.
    }
  }, []);

  // Окно уменьшили — панель не должна закрыть список целиком.
  useEffect(() => {
    const onResize = () => setWidth((value) => clamp(value, window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!dragging) return;

    const onMove = (event: PointerEvent) => {
      // Панель прижата к правому краю, поэтому влево — шире.
      apply(start.current.width + (start.current.x - event.clientX));
    };
    const stop = () => setDragging(false);

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    // Пока тянут, выделять текст незачем: иначе разбор подсвечивается синим.
    const previous = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      document.body.style.userSelect = previous;
      document.body.style.cursor = "";
    };
  }, [dragging, apply]);

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      event.preventDefault();
      start.current = { x: event.clientX, width };
      setDragging(true);
    },
    [width],
  );

  /** Стрелками — по шагу, Home и End — к границам.
   *
   *  Не для галочки: у ручки нет содержимого, и без клавиатуры она недоступна
   *  никому, кто не работает мышью. */
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const step = event.shiftKey ? 120 : 24;
      const moves: Record<string, number> = {
        ArrowLeft: width + step,
        ArrowRight: width - step,
      };
      if (event.key in moves) {
        event.preventDefault();
        apply(moves[event.key]);
      } else if (event.key === "Home") {
        event.preventDefault();
        apply(maxWidth(window.innerWidth));
      } else if (event.key === "End") {
        event.preventDefault();
        apply(MIN_WIDTH);
      }
    },
    [width, apply],
  );

  /** Двойной щелчок возвращает к исходному — быстрее, чем тянуть обратно. */
  const onDoubleClick = useCallback(() => apply(MIN_WIDTH), [apply]);

  return { width, dragging, onPointerDown, onKeyDown, onDoubleClick };
}
