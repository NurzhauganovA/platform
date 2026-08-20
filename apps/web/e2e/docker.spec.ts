/**
 * Проверка собранной платформы в контейнерах.
 *
 * Отдельно от остальных сквозных тестов и по требованию: те идут против
 * сервера разработки на :5173, а этот — против nginx на :8080, где статика
 * уже собрана, а API живёт за прокси. Ровно там ломается то, чего не видно
 * иначе: путь до `/api`, поток событий задачи, отдача книги Excel.
 *
 *   make up
 *   E2E_DOCKER=1 npx playwright test e2e/docker.spec.ts
 */

import { expect, test } from "@playwright/test";

const BASE = process.env.E2E_DOCKER_URL ?? "http://localhost:8080";
const PASSWORD = process.env.E2E_PASSWORD ?? "закупки-2026-каратау";
const ANALYST = process.env.E2E_ANALYST ?? "analyst@fintend.kz";

test.skip(
  !process.env.E2E_DOCKER,
  "Только для собранных контейнеров: E2E_DOCKER=1 после `make up`",
);

test.use({ baseURL: BASE });

test("платформа в контейнерах работает целиком", async ({ page }) => {
  page.on("pageerror", (error) =>
    console.log("ОШИБКА СТРАНИЦЫ:", error.message),
  );

  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(ANALYST);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/skstore/bargains");

  // Заголовок таблицы, а не просто `table`: при переходе между разделами
  // старая таблица ещё в разметке, и счёт строк попал бы по ней.
  await expect(
    page.getByRole("columnheader", { name: "Себестоимость" }),
  ).toBeVisible({
    timeout: 60_000,
  });
  expect(await page.locator("tbody tr").count()).toBeGreaterThan(0);

  await page.getByRole("link", { name: "Предзаказы" }).click();
  await expect(
    page.getByRole("heading", { name: "Предзаказы OMarket" }),
  ).toBeVisible();

  // Список может быть пуст по делу: если приём по всем предзаказам закончился,
  // в рабочем списке им не место. Тогда экран обязан объяснить, почему пусто,
  // а не молчать — это и проверяем.
  const table = page.locator("table");
  const empty = page.getByText(
    /приём уже закончился|Пока пусто|ещё не считали/,
  );
  await table.or(empty).first().waitFor({ timeout: 60_000 });
  if (await table.count()) {
    expect(await page.locator("tbody tr").count()).toBeGreaterThan(0);
  }
});

test("книга Excel отдаётся файлом и не стоит денег", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(ANALYST);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/skstore/bargains");

  const started = Date.now();
  const response = await page.request.get("/api/skstore/export");

  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain("spreadsheetml");
  // Книга собирается по уже посчитанному: без обогащения это секунды. Минута
  // означала бы, что выгрузка снова ходит на склад и в модель, а скачивание
  // отчёта списывать со счёта не должно.
  expect(Date.now() - started).toBeLessThan(30_000);
});
