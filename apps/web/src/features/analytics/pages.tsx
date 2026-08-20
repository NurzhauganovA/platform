/** Обёртки разделов: страница аналитики общая, различаются только подписи. */

import { AnalyticsPage } from "./AnalyticsPage";

export function BargainsAnalytics() {
  return <AnalyticsPage slug="skstore" title="закупы SKStore" />;
}

export function PreordersAnalytics() {
  return <AnalyticsPage slug="omarket" title="предзаказы OMarket" />;
}

export function TenderAnalytics() {
  return <AnalyticsPage slug="tender" title="отбор закупок" />;
}
