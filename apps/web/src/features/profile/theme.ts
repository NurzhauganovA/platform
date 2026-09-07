/**
 * Тема платформы: светлая, тёмная или как в системе.
 *
 * Три положения, а не два. «Как в системе» — это не то же самое, что светлая:
 * у человека тёмная тема включается по расписанию, и платформа, оставшаяся
 * светлой в темноте, светит в глаза одна на весь экран.
 *
 * Выбор помнится на устройстве, а не в учётной записи. За одним компьютером в
 * отделе сидят по очереди, и тема — про глаза и про монитор, а не про то, кто
 * вошёл. Учётная запись при этом ездит с человеком на другой компьютер, где
 * монитор другой.
 *
 * Правила цвета уже написаны в `tokens.css`: `[data-theme]` на корне сильнее
 * системного `prefers-color-scheme`. Здесь только выставляется признак —
 * второй набор цветов в скрипте разошёлся бы с первым на первой же правке.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";

export const THEMES: { key: Theme; title: string }[] = [
  { key: "system", title: "Как в системе" },
  { key: "light", title: "Светлая" },
  { key: "dark", title: "Тёмная" },
];

const SAVED = "fintend:theme";

/** Ставит признак на корень. «Как в системе» — снимает его вовсе. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

/** Что выбрано. Читается до первой отрисовки — иначе экран мигает белым. */
export function savedTheme(): Theme {
  const found = window.localStorage.getItem(SAVED);
  return found === "light" || found === "dark" ? found : "system";
}

export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(savedTheme);

  useEffect(() => applyTheme(theme), [theme]);

  const pick = useCallback((next: Theme) => {
    window.localStorage.setItem(SAVED, next);
    setTheme(next);
  }, []);

  return [theme, pick];
}
