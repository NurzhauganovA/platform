import { expect, test } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "expert.itc.kz@gmail.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "временный-пароль-2026";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  // После входа открывается первый раздел меню — закупы площадки. Тендерный
  // отбор лежит отдельным пунктом, и переходим туда явно.
  await page.waitForURL("**/skstore/bargains");
}

async function openTenders(page: import("@playwright/test").Page) {
  await signIn(page);
  await page.getByRole("link", { name: "Отбор закупок" }).click();
  await page.waitForURL("**/tender/worklist");
}

test("без сессии показывается вход", async ({ page }) => {
  await page.goto("/tender/worklist");

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

test("вход открывает отбор закупок", async ({ page }) => {
  await openTenders(page);

  await expect(
    page.getByRole("heading", { name: "Отбор закупок" }),
  ).toBeVisible();
  // Раздел показывает разобранное, а не предлагает завести закупку: папки
  // разбирают на машине тендерщика.
  await expect(page.getByRole("button", { name: "Новая закупка" })).toHaveCount(
    0,
  );
});

test("меню строится из подключённых модулей", async ({ page }) => {
  await signIn(page);

  // Оболочка не знает ни про площадки, ни про тендеры — пункты приходят
  // из /api/modules. Захардкоженный пункт означал бы сломанный контракт.
  await expect(page.getByRole("link", { name: "Закупы" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Предзаказы" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Отбор закупок" })).toBeVisible();
});

test("разбор закупки открывается из таблицы", async ({ page }) => {
  await openTenders(page);
  // Ждём именно таблицу, а не просто загрузку страницы: до ответа API её
  // ещё нет, и проверка молча пропускалась бы.
  const table = page.locator("table");
  await table
    .or(page.getByText(/Пока (ничего|ни одной)/))
    .first()
    .waitFor();
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  // Отдельной колонки с кнопкой нет — разбор открывает сама строка.
  await page.locator("tbody tr").first().click();

  const panel = page.getByRole("dialog", { name: "Разбор" });
  await expect(panel).toBeVisible();
  // Первый раздел — про саму закупку. Порядок тот же, что на листе разбора.
  //
  // Ждём дольше обычного: разбор считается из общего отбора, и на холодном
  // кэше сервер собирает его несколько секунд. Пять секунд по умолчанию —
  // это терпение теста, а не срок, за который обязана уложиться платформа.
  await expect(panel.getByText("Закупка", { exact: true })).toBeVisible({
    timeout: 20_000,
  });
});

test("выход возвращает на вход", async ({ page }) => {
  await signIn(page);

  await page.getByRole("button", { name: "Выйти" }).click();

  await expect(page).toHaveURL(/login/);
});
