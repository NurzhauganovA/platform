/**
 * Аналитика разделов.
 *
 * Экран один на все три, а данные у них разные: у площадок нет цены всей
 * закупки. Проверяется, что состав подстраивается сам, а не показывает пустые
 * графы там, где считать нечего.
 */

import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "закупки-2026-каратау";
const ANALYST = process.env.E2E_ANALYST ?? "analyst@fintend.kz";
const BUYER = process.env.E2E_BUYER ?? "buyer@fintend.kz";

async function open(page: Page, slug: string, email = ANALYST) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(email);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/skstore/bargains");
  await page.goto(`/${slug}/analytics`);
  // Считается из того же ответа, что рисует таблицу: на холодном кэше сервер
  // собирает его несколько секунд.
  await page
    .getByText(/^Всё по разрезу: |Данные пока недоступны/)
    .first()
    .waitFor({ timeout: 45_000 });
}

/** Есть ли на странице данные, или база раздела недоступна. */
async function ready(page: Page): Promise<boolean> {
  return (await page.getByText("Данные пока недоступны").count()) === 0;
}

test("аналитика есть в меню каждого раздела", async ({ page }) => {
  await open(page, "tender");

  // Пункт приходит из `/api/modules`, как и остальные: захардкоженный означал
  // бы, что следующую площадку придётся вписывать руками.
  await expect(page.getByRole("link", { name: "Аналитика" })).toHaveCount(3);
});

test("тендеры режутся по категориям и показывают объём", async ({ page }) => {
  await open(page, "tender");
  test.skip(!(await ready(page)), "база тендеров недоступна");

  // Категория — разрез по умолчанию: вопрос «в чём мы сильны» задают чаще
  // прочих, и роль этой колонки объявил сам модуль.
  await expect(page.getByText(/^Всё по разрезу: категория/)).toBeVisible();
  await expect(page.getByRole("button", { name: "категория" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // Цена всей закупки есть только у тендеров — графа объёма только здесь.
  await expect(page.getByRole("columnheader", { name: /Объём/ })).toBeVisible();
});

test("у площадки объёма нет, и графы под него тоже", async ({ page }) => {
  await open(page, "skstore");

  // В книге площадки цена за единицу: складывать её по строкам нельзя, и
  // графа, показывающая сумму цен за штуку, врала бы.
  await expect(page.getByRole("columnheader", { name: /Объём/ })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("columnheader", { name: /Заработок/ }),
  ).toBeVisible();
});

test("разрез переключается и живёт в ссылке", async ({ page }) => {
  await open(page, "tender");
  test.skip(!(await ready(page)), "база тендеров недоступна");

  await page.getByRole("button", { name: "название заказчика" }).click();

  await expect(
    page.getByText(/^Всё по разрезу: название заказчика/),
  ).toBeVisible();
  // Ссылкой на разрез делятся так же, как ссылкой на отбор.
  await expect.poll(() => page.url()).toContain("by=nazvanie_zakazchika");
});

test("закупщику деньги не показывают и здесь", async ({ page }) => {
  await open(page, "tender", BUYER);
  test.skip(!(await ready(page)), "база тендеров недоступна");

  // Граница та же, что у таблицы и разбора: сервер вырезал колонки по правам,
  // и считать по ним нечего. Спрятать на экране и посчитать в браузере значит
  // отдать — итог виден и без колонки.
  await expect(
    page.getByRole("columnheader", { name: /Заработок/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("columnheader", { name: /Себестоимость/ }),
  ).toHaveCount(0);
  // Но сама аналитика работает: строки и разрезы ему видны.
  await expect(page.getByText(/^Всё по разрезу: /)).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Строк" })).toBeVisible();
});
