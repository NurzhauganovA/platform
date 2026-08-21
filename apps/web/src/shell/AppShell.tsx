/**
 * Оболочка платформы.
 *
 * Меню строится из `/api/modules` — из того, что модули сами о себе объявили.
 * Оболочка не знает ни про тендеры, ни про SKStore: подключение нового проекта
 * не должно требовать правок здесь, иначе контракт модулей не работает.
 */

import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { auth, platform, type Me } from "@/api/tender";
import { Badge, Button, cx } from "@/ui";

const ROLE_TITLES: Record<string, string> = {
  admin: "Администратор",
  analyst: "Тендерщик",
  buyer: "Закупщик",
  viewer: "Наблюдатель",
};

export function AppShell({ me }: { me: Me }) {
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
      <aside className="flex w-60 shrink-0 flex-col border-r border-hairline bg-surface">
        <div className="border-b border-hairline px-5 py-4">
          <div className="text-base font-semibold tracking-tight text-ink">
            Fintend
          </div>
          {me.organization.name !== "Fintend" && (
            <div className="mt-0.5 text-xs text-ink-muted">
              {me.organization.name}
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {modules.map((module) => (
            <div key={module.slug} className="mb-5">
              <div className="px-2 pb-1.5 text-[11px] font-semibold tracking-wide text-ink-muted uppercase">
                {module.title}
              </div>
              {module.nav.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    cx(
                      "block rounded-[8px] px-2.5 py-1.5 text-sm transition",
                      isActive
                        ? "bg-series-1/10 font-medium text-series-1"
                        : "text-ink-secondary hover:bg-plane hover:text-ink",
                    )
                  }
                >
                  {item.title}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="border-t border-hairline px-4 py-3.5">
          <div className="truncate text-sm text-ink" title={me.email}>
            {me.full_name || me.email}
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2">
            <Badge tone="info">{ROLE_TITLES[me.role] ?? me.role}</Badge>
            <button
              onClick={() => logout.mutate()}
              className="text-xs text-ink-muted transition hover:text-ink"
            >
              Выйти
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
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
