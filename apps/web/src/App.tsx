/**
 * Маршруты и вход в приложение.
 *
 * Пока не выяснено, кто пришёл, интерфейс не рисуется вовсе: иначе на миг
 * показывается пустая оболочка, а потом её сменяет форма входа.
 *
 * Адреса латиницей, хотя интерфейс русский. Кириллица в пути превращается в
 * «/%D0%B2%D1%85%D0%BE%D0%B4» при копировании ссылки, в логах и в переписке —
 * адрес перестаёт читаться именно там, где им делятся.
 */

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { auth } from "@/api/tender";
import { ApiError } from "@/api/client";
import { AppShell } from "@/shell/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import { CasesPage } from "@/features/tender/CasesPage";
import { NewCasePage } from "@/features/tender/NewCasePage";
import { CasePage } from "@/features/tender/CasePage";
import { Spinner } from "@/ui";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) =>
        // Повторять запрос без сессии бессмысленно: ответ не изменится,
        // а человек ждёт форму входа.
        !(error instanceof ApiError && (error.isUnauthorized || error.isForbidden)) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});

function Routing() {
  const { data: me, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: auth.me,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-plane">
        <Spinner label="Проверяем доступ…" />
      </div>
    );
  }

  if (!me) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<AppShell me={me} />}>
        <Route index element={<Navigate to="/tender/cases" replace />} />
        <Route path="tender/cases" element={<CasesPage />} />
        <Route path="tender/cases/new" element={<NewCasePage />} />
        <Route path="tender/cases/:caseId" element={<CasePage />} />
      </Route>
      <Route path="/login" element={<Navigate to="/tender/cases" replace />} />
      <Route path="*" element={<Navigate to="/tender/cases" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <Routing />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
