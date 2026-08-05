import { expect, test } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "expert.itc.kz@gmail.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "временный-пароль-2026";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/tender/cases");
}

test("без сессии показывается вход", async ({ page }) => {
  await page.goto("/tender/cases");

  await expect(page).toHaveURL(/login/);
  await expect(page.getByRole("button", { name: "Войти" })).toBeVisible();
});

test("неверный пароль не пускает и не выдаёт причину", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(EMAIL);
  await page.locator('input[type="password"]').fill("неверный пароль совсем");
  await page.getByRole("button", { name: "Войти" }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  // Сообщение одинаково на все причины: иначе форма подсказывает, кто у нас
  // работает, а по адресам сотрудников строят фишинг.
  await expect(alert).toContainText("Неверная почта или пароль");
});

test("вход открывает список закупок", async ({ page }) => {
  await signIn(page);

  await expect(page.getByRole("heading", { name: "Закупки" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Новая закупка" })).toBeVisible();
});

test("меню строится из подключённых модулей", async ({ page }) => {
  await signIn(page);

  // Оболочка не знает про тендеры — пункты приходят из /api/modules.
  await expect(page.getByRole("link", { name: "Закупки" })).toBeVisible();
  await expect(page.getByRole("link", { name: "История цен" })).toBeVisible();
});

test("карточка закупки показывает состав", async ({ page }) => {
  await signIn(page);
  // Ждём именно список, а не просто загрузку страницы: до ответа API
  // таблицы ещё нет, и проверка молча пропускалась бы.
  const table = page.locator("table");
  await table.or(page.getByText("Пока ни одной закупки")).first().waitFor();
  test.skip((await table.count()) === 0, "в базе нет закупок");

  const first = page.locator("table a").first();

  await first.click();

  await expect(page.getByText("Документов")).toBeVisible();
  await expect(page.getByRole("button", { name: /Разобрать|Разбираем/ })).toBeVisible();
});

test("выход возвращает на вход", async ({ page }) => {
  await signIn(page);

  await page.getByRole("button", { name: "Выйти" }).click();

  await expect(page).toHaveURL(/login/);
});
