/**
 * Оболочка платформы.
 *
 * Меню строится из `/api/modules` — из того, что модули сами о себе объявили.
 * Оболочка не знает ни про тендеры, ни про SKStore: подключение нового проекта
 * не должно требовать правок здесь, иначе контракт модулей не работает.
 *
 * Значок пункта тоже приходит от модуля именем (`NavItem.icon`), а рисуется
 * здесь (`icons.tsx`). Так оболочка остаётся глухой к разделам, но ряд
 * пунктов выглядит одной рукой нарисованным: набор значков, собранный по
 * месту в каждом модуле, разошёлся бы в манере на второй же площадке.
 *
 * Колонка сворачивается до значков. Разделов уже полтора десятка, а работают
 * в основном в одном: сложенная колонка отдаёт таблице лотов ещё двести точек
 * ширины, и это две колонки цифр, ради которых иначе крутят вбок. Выбор
 * помнится между заходами — свернул человек не для этой страницы, а вообще.
 */

import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  auth,
  platform,
  type Me,
  type NavItem,
  type PlatformModule,
} from "@/api/tender";
import { Badge, Button, cx } from "@/ui";
import { NavIcon } from "./icons";

const ROLE_TITLES: Record<string, string> = {
  admin: "Администратор",
  analyst: "Тендерщик",
  buyer: "Закупщик",
  viewer: "Наблюдатель",
};

/** Сложена колонка или нет. Решение человека, а не страницы. */
const FOLDED = "fintend:nav-folded";

export function AppShell({ me }: { me: Me }) {
  const [folded, setFolded] = useState(
    () => window.localStorage.getItem(FOLDED) === "1",
  );

  const fold = (next: boolean) => {
    setFolded(next);
    window.localStorage.setItem(FOLDED, next ? "1" : "0");
  };

  const { data: modules = [] } = useQuery({
    queryKey: ["modules"],
    queryFn: platform.modules,
    // Состав модулей меняется с выкладкой, а не в течение сессии.
    staleTime: 60 * 60 * 1000,
  });

  const logout = useMutation({
    mutationFn: auth.logout,
    // Полная перезагрузка, а не переход внутри приложения. Выход должен
    // стирать всё, что осталось от предыдущего человека: в памяти вкладки
    // лежат закупки, себестоимость и маржа, и за одним компьютером в отделе
    // сидят по очереди.
    onSettled: () => window.location.assign("/login"),
  });

  return (
    <div className="flex min-h-screen bg-plane">
      <aside
        className={cx(
          "sticky top-0 flex h-screen shrink-0 flex-col border-r border-hairline bg-surface",
          "transition-[width] duration-200 ease-out",
          folded ? "w-[68px]" : "w-64",
        )}
      >
        {/* Шапка: знак платформы и кнопка складывания. Кнопка здесь, а не
            внизу: сворачивают в начале работы, а не после прокрутки меню. */}
        <div
          className={cx(
            "flex h-16 shrink-0 items-center gap-2 border-b border-hairline",
            folded ? "justify-center px-2" : "px-4",
          )}
        >
          {!folded && (
            <div className="min-w-0 flex-1">
              <div className="truncate text-[15px] font-semibold tracking-tight text-ink">
                Fintend
              </div>
              {me.organization.name !== "Fintend" && (
                <div className="truncate text-[11px] text-ink-muted">
                  {me.organization.name}
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={() => fold(!folded)}
            aria-expanded={!folded}
            title={folded ? "Развернуть меню" : "Свернуть меню"}
            className={cx(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px]",
              "text-ink-muted transition hover:bg-plane hover:text-ink",
              "focus-visible:outline focus-visible:outline-2",
              "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
            )}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden
            >
              <path
                d="M3.5 5.5h17M3.5 12h17M3.5 18.5h17"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <nav
          className={cx(
            "flex-1 overflow-x-hidden overflow-y-auto py-3",
            folded ? "px-2" : "px-3",
          )}
        >
          {grouped(modules).map(([group, items], at) => (
            <div key={group} className="mb-4 last:mb-0">
              {/* Свёрнутой колонке название раздела не влезает, а совсем без
                  разделителя пункты сливаются в одну ленту из пятнадцати.
                  Черта по номеру группы, а не по `first:`: каждая черта —
                  первый ребёнок своего блока, и правило срабатывало на всех,
                  включая верхнюю, где отделять не от чего. */}
              {folded ? (
                at > 0 && (
                  <div className="mx-2 mb-2.5 border-t border-hairline" />
                )
              ) : (
                <div className="px-2.5 pb-1 text-[10.5px] font-semibold tracking-[0.08em] text-ink-muted uppercase">
                  {group}
                </div>
              )}
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.path}>
                    <NavLink
                      to={item.path}
                      title={folded ? item.title : undefined}
                      className={({ isActive }) =>
                        cx(
                          "group relative flex items-center rounded-[9px] text-sm transition",
                          "focus-visible:outline focus-visible:outline-2",
                          "focus-visible:-outline-offset-2 focus-visible:outline-series-1",
                          folded
                            ? "h-9 justify-center px-0"
                            : "gap-2.5 px-2.5 py-2",
                          isActive
                            ? "bg-series-1/10 font-medium text-series-1"
                            : "text-ink-secondary hover:bg-plane hover:text-ink",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {/* Чёрточка у края — второй признак выбранного
                              пункта рядом с заливкой: при дальтонизме синяя
                              подложка на светлом фоне почти не читается. */}
                          <span
                            aria-hidden
                            className={cx(
                              "absolute top-1/2 left-0 h-5 w-[3px] -translate-y-1/2 rounded-r-full",
                              "transition-opacity",
                              isActive
                                ? "bg-series-1 opacity-100"
                                : "opacity-0",
                            )}
                          />
                          <NavIcon name={item.icon} />
                          {!folded && (
                            <span className="min-w-0 flex-1 truncate">
                              {item.title}
                            </span>
                          )}
                        </>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div
          className={cx(
            "shrink-0 border-t border-hairline",
            folded ? "px-2 py-3" : "px-3 py-3",
          )}
        >
          {folded ? (
            // Кружок ведёт в профиль, а не гасит сессию. Выход рядом отдельной
            // кнопкой: одно нажатие мимо не должно выкидывать из платформы.
            <div className="flex flex-col items-center gap-1.5">
              <NavLink
                to="/profile"
                title={`${me.full_name || me.email} · профиль`}
                className={({ isActive }) =>
                  cx(
                    "flex h-9 w-9 items-center justify-center rounded-full text-xs font-semibold transition",
                    isActive
                      ? "bg-series-1 text-white"
                      : "bg-series-1/10 text-series-1 hover:bg-series-1/20",
                  )
                }
              >
                {initials(me.full_name || me.email)}
              </NavLink>
              <button
                type="button"
                onClick={() => logout.mutate()}
                title="Выйти"
                className="rounded-[8px] p-1 text-ink-muted transition hover:bg-critical/10 hover:text-critical"
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M15 4.5h3.5A1.5 1.5 0 0 1 20 6v12a1.5 1.5 0 0 1-1.5 1.5H15M10 8l-4 4 4 4M6 12h9"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2.5 rounded-[9px] px-1.5 py-1">
              {/* Имя ведёт в профиль. Туда заходят редко и с разными поводами —
                  привязать Телеграм, сменить пароль, переключить тему, — и
                  отдельный пункт меню ради этого занимал бы строку каждый
                  день ради нажатия раз в месяц. */}
              <NavLink
                to="/profile"
                title="Профиль: уведомления, пароль, тема"
                className={({ isActive }) =>
                  cx(
                    "flex min-w-0 flex-1 items-center gap-2.5 rounded-[8px] px-1 py-1 transition",
                    isActive ? "bg-series-1/10" : "hover:bg-plane",
                  )
                }
              >
                <span
                  aria-hidden
                  className={cx(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                    "bg-series-1/10 text-xs font-semibold text-series-1",
                  )}
                >
                  {initials(me.full_name || me.email)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-ink">
                    {me.full_name || me.email}
                  </span>
                  <span className="mt-0.5 block">
                    <Badge tone="info">{ROLE_TITLES[me.role] ?? me.role}</Badge>
                  </span>
                </span>
              </NavLink>
              <button
                onClick={() => logout.mutate()}
                title="Выйти"
                className={cx(
                  "shrink-0 rounded-[8px] p-1.5 text-ink-muted transition",
                  "hover:bg-critical/10 hover:text-critical",
                )}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M15 4.5h3.5A1.5 1.5 0 0 1 20 6v12a1.5 1.5 0 0 1-1.5 1.5H15M10 8l-4 4 4 4M6 12h9"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

/** Две буквы для кружка. Имя целиком в круг не влезает, а лицо узнают по ним. */
function initials(name: string): string {
  const parts = name
    .trim()
    .split(/[\s@.]+/)
    .filter(Boolean);
  const letters = parts.slice(0, 2).map((part) => part[0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

/**
 * Раскладка меню по разделам.
 *
 * Раздел задаёт сам пункт, а не модуль, которому он принадлежит. Группировка
 * по источнику данных разносила работу одного человека по трём местам:
 * менеджер утром смотрит свой стол, потом лоты, потом согласование — а они
 * лежали в «Работе», «Тендерах» и «Госзакупках».
 *
 * Порядок разделов — порядок их первого появления, то есть порядок, в каком
 * их объявили модули. Сортировать по алфавиту значит поставить «Площадки»
 * впереди «Моего стола».
 */
function grouped(modules: PlatformModule[]): [string, NavItem[]][] {
  const groups = new Map<string, NavItem[]>();
  for (const module of modules) {
    for (const item of module.nav) {
      const key = item.group || module.title;
      const bucket = groups.get(key);
      if (bucket) bucket.push(item);
      else groups.set(key, [item]);
    }
  }
  return [...groups.entries()];
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-6 border-b border-hairline bg-surface px-8 py-5">
      <div className="min-w-0">
        <h1 className="truncate text-lg font-semibold tracking-tight text-ink">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-0.5 truncate text-sm text-ink-muted">{subtitle}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </header>
  );
}

export { Button };
