/**
 * Запросы тендерного модуля.
 *
 * Типы описаны здесь, а не выведены из ответа: по ним видно, что интерфейс
 * ожидает от API. Точные формы генерируются из OpenAPI (`npm run api:types`)
 * и служат проверкой — расхождение всплывает при сборке, а не у человека
 * на экране.
 */

import { api } from "./client";

export type Role = "admin" | "analyst" | "buyer" | "viewer";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  organization: { id: string; name: string; slug: string };
  last_login_at: string | null;
}

export type CaseStatus =
  "draft" | "ready" | "analyzing" | "analyzed" | "archived";

export interface TenderCase {
  id: string;
  title: string;
  customer: string;
  subject: string;
  status: CaseStatus;
  files_count: number;
  total_bytes: number;
  note: string;
}

export interface CaseFile {
  id: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
}

export interface CaseDetail extends TenderCase {
  files: CaseFile[];
}

export interface FileProbe {
  name: string;
  relative_path: string;
  size_bytes: number;
  sha256: string;
}

export interface FileVerdict {
  relative_path: string;
  supported: boolean;
  known: boolean;
  analysis_cached: boolean;
  reason: string;
}

export interface UploadPlan {
  files: FileVerdict[];
  total: number;
  to_upload: number;
  upload_bytes: number;
  skipped_known: number;
  skipped_unsupported: number;
  already_analyzed: number;
}

export type JobStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  module: string;
  kind: string;
  status: JobStatus;
  done: number;
  total: number;
  percent: number;
  note: string;
  result: Record<string, unknown> | null;
  error: string | null;
  cost_usd: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Quote {
  supplier: string | null;
  document: string;
  specification: string | null;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
  total_price: number | null;
  is_cheapest: boolean;
}

export interface Position {
  name: string;
  quotes: Quote[];
  min_price: number | null;
  max_price: number | null;
  median_price: number | null;
  spread_ratio: number | null;
  supplier_count: number;
}

export interface Decision {
  recommendation: string | null;
  confidence: string | null;
  summary: string;
  comparability: string;
  best_offer_supplier: string | null;
  best_offer_reason: string | null;
  estimated_cost: number | null;
  recommended_bid: number | null;
  expected_margin_percent: number | null;
  margin_reasoning: string;
  blockers: string[];
  questions: string[];
}

export interface Finding {
  position: string;
  country: string;
  marketplace: string;
  supplier: string | null;
  title: string;
  price_kzt: number | null;
  landed_cost: number | null;
  unit: string | null;
  delivery_days: number | null;
  min_order: string | null;
  url: string | null;
  contact: string | null;
  matches_spec: boolean;
  match_note: string;
  margin_percent: number | null;
  margin_total: number | null;
}

export interface Market {
  searched: boolean;
  findings: Finding[];
  total_margin: number | null;
  by_country: Record<string, number>;
}

export interface RequestedPosition {
  name: string;
  specification: string | null;
  quantity: number | null;
  unit: string | null;
  customer_price: number | null;
  source_document: string;
}

export interface CaseComparison {
  case_id: string;
  subject: string | null;
  customer: string | null;
  documents: number;
  offers: number;
  positions: Position[];
  requirements: string[];
  risks: string[];
  total_min: number | null;
  total_max: number | null;
  /** Что нужно заказчику — когда предложений ещё нет. */
  requested: RequestedPosition[];
  market: Market | null;
  /** Отсутствует у закупщика и наблюдателя: там себестоимость и маржа. */
  decision: Decision | null;
  analyzed: boolean;
}

export interface Company {
  key: string;
  name: string;
  bin: string;
  director: string;
  is_default: boolean;
  missing: string[];
  notes: string;
}

export interface ModuleHealth {
  ok: boolean;
  core_version: string;
  provider: string;
  model_access: boolean;
  companies_configured: number;
  problems: string[];
}

export interface NavItem {
  title: string;
  path: string;
  icon: string | null;
}

export interface PlatformModule {
  slug: string;
  title: string;
  description: string;
  nav: NavItem[];
}

export const auth = {
  me: () => api.get<Me>("/api/auth/me"),
  login: (email: string, password: string) =>
    api.post<Me>("/api/auth/login", { email, password }),
  logout: () => api.post<{ ok: boolean }>("/api/auth/logout"),
};

export const platform = {
  modules: () => api.get<PlatformModule[]>("/api/modules"),
};

export const tender = {
  health: () => api.get<ModuleHealth>("/api/tender/health"),
  companies: () => api.get<Company[]>("/api/tender/companies"),

  cases: () => api.get<TenderCase[]>("/api/tender/cases"),
  case: (id: string) => api.get<CaseDetail>(`/api/tender/cases/${id}`),
  comparison: (id: string) =>
    api.get<CaseComparison>(`/api/tender/cases/${id}/comparison`),
  createCase: (payload: {
    title: string;
    customer?: string;
    subject?: string;
  }) => api.post<TenderCase>("/api/tender/cases", payload),
  attachFiles: (
    id: string,
    files: { file_id: string; relative_path: string }[],
  ) => api.post<CaseDetail>(`/api/tender/cases/${id}/files`, files),
  analyze: (id: string, force = false) =>
    api.post<{ job_id: string }>(
      `/api/tender/cases/${id}/analyze?force=${force}`,
    ),
  splitPreview: (id: string) =>
    api.get<{
      can_split: boolean;
      reason: string;
      cases: {
        title: string;
        subject: string;
        customer: string;
        files: string[];
        anchors: number;
        offers: number;
      }[];
    }>(`/api/tender/cases/${id}/split`),
  split: (id: string) =>
    api.post<TenderCase[]>(`/api/tender/cases/${id}/split`),
  sourcing: (id: string, force = false) =>
    api.post<{ job_id: string }>(
      `/api/tender/cases/${id}/sourcing?force=${force}`,
    ),
  offer: (
    id: string,
    payload: { companies: string[]; number: string | null },
  ) => api.post<{ job_id: string }>(`/api/tender/cases/${id}/offer`, payload),
  documents: (id: string) =>
    api.get<{ name: string; size_bytes: number; kind: string }[]>(
      `/api/tender/cases/${id}/documents`,
    ),
  decide: (id: string, withMarket = false) =>
    api.post<{ job_id: string }>(
      `/api/tender/cases/${id}/decide?with_market=${withMarket}`,
    ),

  uploadPlan: (probes: FileProbe[]) =>
    api.post<UploadPlan>("/api/tender/upload-plan", probes),
  lookupFiles: (hashes: string[]) =>
    api.post<{ id: string; sha256: string; size_bytes: number }[]>(
      "/api/tender/files/lookup",
      hashes,
    ),
  uploadFile: (file: File, relativePath: string, sha256: string) => {
    const form = new FormData();
    form.append("sha256", sha256);
    form.append("relative_path", relativePath);
    form.append("file", file);
    return api.upload<{ id: string; sha256: string; size_bytes: number }>(
      "/api/tender/files",
      form,
    );
  },
};

export const jobs = {
  list: (module?: string) =>
    api.get<Job[]>(`/api/jobs${module ? `?module=${module}` : ""}`),
  get: (id: string) => api.get<Job>(`/api/jobs/${id}`),
  cancel: (id: string) => api.post<Job>(`/api/jobs/${id}/cancel`),
};
