/** Закупы SKStore. Тонкая обёртка: экран общий для обеих площадок. */

import { WorklistPage } from "./WorklistPage";

export function BargainsPage() {
  return (
    <WorklistPage
      slug="skstore"
      title="Закупы SKStore"
      subtitle="Самрук-Қазына: что брать сегодня и почём мы это купим"
      unit="закупов"
    />
  );
}
