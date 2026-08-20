/** Предзаказы OMarket. Тонкая обёртка: экран общий для обеих площадок. */

import { WorklistPage } from "./WorklistPage";

export function PreordersPage() {
  return (
    <WorklistPage
      slug="omarket"
      title="Предзаказы OMarket"
      subtitle="OMarket.kz: что успеть до срока и сколько на этом заработаем"
      unit="предзаказов"
    />
  );
}
