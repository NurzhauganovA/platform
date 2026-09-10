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

import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { auth, platform } from "@/api/tender";
import { ApiError } from "@/api/client";
import { AppShell } from "@/shell/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import { BargainsPage } from "@/features/worklist/BargainsPage";
import { CardPage } from "@/features/cards/CardPage";
import { LotsPage } from "@/features/cards/LotsPage";
import { ApprovalPage } from "@/features/cards/ApprovalPage";
import { SubmitPage } from "@/features/cards/SubmitPage";
import {
  AnalysisDesk,
  DiscussionDesk,
  LegalDesk,
  SupplyDesk,
} from "@/features/cards/DeskPage";
import { CodesPage } from "@/features/goszakup/CodesPage";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { NotifyPage } from "@/features/notify/NotifyPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { GoszakupPage } from "@/features/worklist/GoszakupPage";
import { RemarkPage } from "@/features/remarks/RemarkPage";
import { RemarksPage } from "@/features/remarks/RemarksPage";
import { PreordersPage } from "@/features/worklist/PreordersPage";
import { TenderPage } from "@/features/worklist/TenderPage";
import { WorkPage } from "@/features/works/WorkPage";
import { WorksPage } from "@/features/works/WorksPage";
import {
  BargainsAnalytics,
  PreordersAnalytics,
  TenderAnalytics,
} from "@/features/analytics/pages";
import { EmptyState, Spinner } from "@/ui";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) =>
        // Повторять запрос без сессии бессмысленно: ответ не изменится,
        // а человек ждёт форму входа.
        !(
          error instanceof ApiError &&
          (error.isUnauthorized || error.isForbidden)
        ) && count < 2,
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
        <Route index element={<Landing />} />
        <Route path="profile" element={<ProfilePage me={me} />} />
        <Route path="skstore/bargains" element={<BargainsPage />} />
        <Route path="omarket/preorders" element={<PreordersPage />} />
        <Route path="tender/worklist" element={<TenderPage />} />
        <Route path="skstore/analytics" element={<BargainsAnalytics />} />
        <Route path="omarket/analytics" element={<PreordersAnalytics />} />
        <Route path="tender/analytics" element={<TenderAnalytics />} />
        <Route path="work/lots" element={<LotsPage />} />
        <Route path="work/lots/:id" element={<CardPage />} />
        <Route path="work/discussion" element={<DiscussionDesk />} />
        <Route path="work/analysis" element={<AnalysisDesk />} />
        <Route path="work/supply" element={<SupplyDesk />} />
        <Route path="work/legal" element={<LegalDesk />} />
        <Route path="work/approval" element={<ApprovalPage />} />
        <Route path="work/audit" element={<AuditPage />} />
        <Route path="work/notifications" element={<NotifyPage />} />
        <Route path="work/submit" element={<SubmitPage />} />
        <Route path="goszakup/lots" element={<GoszakupPage />} />
        <Route path="goszakup/codes" element={<CodesPage />} />
        <Route path="goszakup/remarks" element={<RemarksPage />} />
        <Route path="goszakup/remarks/:id" element={<RemarkPage />} />
        <Route path="tender/works" element={<WorksPage role={me.role} />} />
        <Route path="tender/works/:id" element={<WorkPage role={me.role} />} />
        {/*
          Заведение закупки папкой убрано с глаз, а не удалено: страницы
          (`features/tender/CasesPage` и соседние) и эндпоинты
          (`/api/tender/cases`) на месте и рабочие. Разбор пока идёт у
          тендерщика на машине, где лежат сами папки, и маршрут вернётся,
          когда они поедут через платформу.
        */}
      </Route>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/**
 * Куда попадает человек, войдя.
 *
 * В первый доступный ему пункт меню, а не в зашитый адрес. Зашитый вёл
 * закупщика и тендерщика в их раздел, а юриста, технолога и сборщика — в
 * чужой, где эндпоинт отвечает отказом: человек видел пустой экран сразу
 * после входа и не понимал, сломалось ли что-то.
 *
 * Меню уже в кэше запросов — оболочка запросила его для боковой панели, — так
 * что лишнего похода в сеть тут нет.
 */
function Landing() {
  const { data: modules, isLoading } = useQuery({
    queryKey: ["modules"],
    queryFn: platform.modules,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner label="Открываем…" />
      </div>
    );
  }

  const first = modules?.flatMap((module) => module.nav)[0];
  if (!first) {
    return (
      <div className="px-8 py-6">
        <EmptyState
          title="Разделов пока нет"
          description="Вашей роли не открыт ни один раздел. Обратитесь к администратору."
        />
      </div>
    );
  }
  return <Navigate to={first.path} replace />;
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
