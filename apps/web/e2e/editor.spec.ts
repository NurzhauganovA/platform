import { expect, test } from "@playwright/test";

const EMAIL = "probe-editor@fintend.kz";
const PASSWORD = "редактор-2026-проверка";

test("ссылка и цвет ставятся на выделенное с клавиатуры", async ({ page }) => {
  page.on("pageerror", (error) =>
    console.log("ОШИБКА СТРАНИЦЫ:", error.message),
  );

  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));

  await page.goto("/work/lots");
  await page.locator("li a[href^='/work/lots/']").first().click();
  await page.waitForURL(/\/work\/lots\/[0-9a-f-]+$/);

  await page.getByRole("button", { name: "Разбор", exact: true }).click();

  // Первая наша ячейка: пишем текст.
  const cell = page.getByRole("textbox", { name: "марка и модель" }).first();
  await cell.click();
  await cell.fill("");
  await page.keyboard.type("Насос ЦНС 60-330");

  // Выделяем с клавиатуры — именно это и не работало.
  await page.keyboard.press("Home");
  for (let i = 0; i < 5; i += 1) await page.keyboard.press("Shift+ArrowRight");

  const bar = page.locator("[data-rich-bar]");
  await expect(bar).toBeVisible({ timeout: 5000 });

  // Ссылка — через поле на странице, не через окно браузера.
  await bar.getByTitle("Ссылка на выделенном").click();
  const field = page.getByLabel("Адрес ссылки");
  await expect(field).toBeVisible();
  await field.fill("https://kaspi.kz/item");
  await bar.getByRole("button", { name: "Вставить" }).click();

  const made = cell.locator("a[href='https://kaspi.kz/item']");
  await expect(made).toHaveCount(1);
  // Ссылка должна выглядеть ссылкой прямо в поле: синей и подчёркнутой. Без
  // этого созданный `<a>` ничем не отличался от текста — и человек, поставивший
  // ссылку, видел ровно то же, что и до неё.
  await expect(made).toHaveCSS("text-decoration-line", "underline");
  const синий = await made.evaluate(
    (node) => window.getComputedStyle(node).color,
  );
  expect(синий).not.toBe("rgb(11, 11, 11)");
  // И адрес не должен появиться в тексте: на пустом выделении браузер вставляет
  // его текстом, и именно так поломка и выглядела.
  await expect(cell).not.toContainText("https://kaspi.kz/item");

  // Цвет на другом выделении.
  await cell.click();
  await page.keyboard.press("End");
  for (let i = 0; i < 6; i += 1) await page.keyboard.press("Shift+ArrowLeft");
  await expect(bar).toBeVisible();
  await bar.getByTitle("Цвет выделенного").click();
  await bar.getByTitle("Не сходится").click();

  await expect(cell.locator("span[style*='color']")).toHaveCount(1);

  // Правка не сбивает курсор: печатаем ещё и проверяем, что текст дописался
  // в конец, а не встал в начало.
  await cell.click();
  await page.keyboard.press("End");
  await page.keyboard.type(" — проверено");
  await expect(cell).toContainText("— проверено");

  // Уходим из поля: на выходе разметка вычищается, у ссылки появляются
  // target и rel — по ней можно перейти.
  await page
    .getByRole("button", { name: "Данные закупки" })
    .click({ trial: true });
  await cell.blur();
  const link = cell.locator("a").first();
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", /noreferrer/);

  // И то же после сохранения на сервере: перезагружаем страницу.
  await page.waitForTimeout(2000);
  await page.reload();
  await page.getByRole("button", { name: "Разбор", exact: true }).click();
  const again = page.getByRole("textbox", { name: "марка и модель" }).first();
  await expect(again.locator("a[href='https://kaspi.kz/item']")).toHaveCount(1);
  await expect(again.locator("span[style*='color']")).toHaveCount(1);
});

test("в обсуждении то же поле и та же полоса", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));

  await page.goto("/work/lots");
  await page.locator("li a[href^='/work/lots/']").first().click();
  await page
    .getByRole("button", { name: "Обсуждение", exact: true })
    .first()
    .click();

  const field = page
    .getByRole("textbox")
    .filter({ hasNot: page.locator("input") })
    .first();
  await field.click();
  await page.keyboard.type("Пункт 3.2 сужает круг участников");
  await page.keyboard.press("Home");
  for (let i = 0; i < 9; i += 1) await page.keyboard.press("Shift+ArrowRight");

  await expect(page.locator("[data-rich-bar]")).toBeVisible({ timeout: 5000 });
});

test("ссылка ставится и на уже размеченном тексте", async ({ page }) => {
  // Именно этот порядок и ломался: в ячейке уже была разметка, чистка на
  // выходе из поля подменяла содержимое целиком, запомненное выделение
  // указывало на исчезнувшие узлы — и браузер вставлял адрес текстом.
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));

  await page.goto("/work/lots");
  await page.locator("li a[href^='/work/lots/']").first().click();
  await page.getByRole("button", { name: "Разбор", exact: true }).click();

  const cell = page
    .getByRole("textbox", { name: "чем отвечает требованию" })
    .first();
  await cell.click();
  await cell.fill("");
  await page.keyboard.type("8 ядер, 2.5 ГГц");

  const bar = page.locator("[data-rich-bar]");

  // Сначала цвет — в ячейке появляется разметка.
  await page.keyboard.press("Home");
  for (let i = 0; i < 6; i += 1) await page.keyboard.press("Shift+ArrowRight");
  await expect(bar).toBeVisible({ timeout: 5000 });
  await bar.getByTitle("Цвет выделенного").click();
  await bar.getByTitle("Подтверждено").click();
  await expect(cell.locator("span[style*='color']")).toHaveCount(1);

  // Теперь ссылка на другом куске той же ячейки.
  await cell.click();
  await page.keyboard.press("End");
  for (let i = 0; i < 4; i += 1) await page.keyboard.press("Shift+ArrowLeft");
  await expect(bar).toBeVisible();
  await bar.getByTitle("Ссылка на выделенном").click();
  await page.getByLabel("Адрес ссылки").fill("https://forcecom.kz/catalog");
  await bar.getByRole("button", { name: "Вставить" }).click();

  await expect(
    cell.locator("a[href='https://forcecom.kz/catalog']"),
  ).toHaveCount(1);
  // Адрес не должен оказаться в тексте — ни целиком, ни хвостом.
  await expect(cell).not.toContainText("forcecom.kz/catalog");
  // И цвет на месте: одно не должно стирать другое.
  await expect(cell.locator("span[style*='color']")).toHaveCount(1);
});
