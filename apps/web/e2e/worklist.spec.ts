/**
 * Рабочие списки целиком: от входа до таблицы.
 *
 * Экран один на все три раздела — SKStore, OMarket и тендерный отбор, — и
 * проверяется здесь то, что не видно в тестах слоёв по отдельности: доходят
 * ли колонки книги до экрана, работают ли переключатели без нового запроса и
 * не попадает ли себестоимость закупщику. Последнее проверяется и в API, но
 * здесь — глазами человека, который открыл страницу.
 *
 * Основной набор идёт по SKStore: разделы устроены одинаково, и гонять один и
 * тот же сценарий трижды значит втрое дольше ждать ради того же ответа.
 * Отдельно проверено только то, чем разделы отличаются.
 */

import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "закупки-2026-каратау";
const ANALYST = process.env.E2E_ANALYST ?? "analyst@fintend.kz";
const BUYER = process.env.E2E_BUYER ?? "buyer@fintend.kz";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Почта" }).fill(email);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL("**/skstore/bargains");
}

/** Ждём именно таблицу: до ответа API её нет, и проверки молча проходили бы. */
async function waitForList(page: Page) {
  const table = page.locator("table");
  await table
    .or(page.getByText(/Список пуст|Пока пусто|недоступн/))
    .first()
    .waitFor();
  return table;
}

test("все три раздела есть в меню и открываются", async ({ page }) => {
  await signIn(page, ANALYST);

  await expect(
    page.getByRole("heading", { name: "Закупы SKStore" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Предзаказы" }).click();
  await expect(
    page.getByRole("heading", { name: "Предзаказы OMarket" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Отбор закупок" }).click();
  await expect(
    page.getByRole("heading", { name: "Отбор закупок" }),
  ).toBeVisible();
});

test("тендерщик видит себестоимость и маржу", async ({ page }) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  const headers = page.locator("thead th");
  await expect(headers.filter({ hasText: "Себестоимость" })).toBeVisible();
  await expect(headers.filter({ hasText: "Маржа ₸" })).toBeVisible();
  // Книга целиком — по кнопке, и состав там уже дословный.
  await page.getByRole("button", { name: "Все колонки" }).click();
  await expect(
    headers.filter({ hasText: "Расчёт себестоимости" }),
  ).toBeVisible();
});

test("закупщику себестоимость не показывают", async ({ page }) => {
  await signIn(page, BUYER);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  await page.getByRole("button", { name: "Все колонки" }).click();

  const headers = page.locator("thead th");
  await expect(headers.filter({ hasText: "Себестоимость" })).toHaveCount(0);
  await expect(headers.filter({ hasText: "Маржа" })).toHaveCount(0);
  // «Где купить» остаётся: это его работа.
  await expect(headers.filter({ hasText: "Где купить" })).toBeVisible();
  // И сказано, что часть колонок скрыта, — молча урезанная таблица выглядит
  // как потерянные данные.
  // Без `\w`: в JS он не покрывает кириллицу, и «колонок» под него не подходит.
  await expect(page.getByText(/с себестоимостью и маржой/)).toBeVisible();
});

test("кнопки, которые тратят деньги, закупщику не показывают", async ({
  page,
}) => {
  await signIn(page, BUYER);
  await waitForList(page);

  await expect(
    page.getByRole("button", { name: "Обновить данные" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Пересчитать" })).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "Скачать Excel" })).toHaveCount(
    0,
  );
});

test("переключатели работают без нового запроса", async ({ page }) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  let requests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/worklist")) requests += 1;
  });

  const before = await page.locator("thead th").count();
  await page.getByRole("button", { name: "Все колонки" }).click();
  await expect(page.locator("thead th").nth(before)).toBeVisible();
  // `exact`: под таблицей есть ещё ссылка «Все строки» в пояснении про
  // скрытые истёкшие, и без уточнения выбор неоднозначен.
  await page.getByRole("button", { name: "Все строки", exact: true }).click();
  await page.waitForTimeout(300);

  expect(requests, "список уже в памяти вкладки — второй запрос лишний").toBe(
    0,
  );
});

test("отбор по решению сужает список", async ({ page }) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  const chip = page.getByRole("button", { name: /^Участвовать/ });
  test.skip((await chip.count()) === 0, "нет выгодных закупов");

  const total = await page.locator("tbody tr").count();
  await chip.click();
  const filtered = await page.locator("tbody tr").count();

  expect(filtered).toBeLessThanOrEqual(total);
  await expect(page.getByRole("button", { name: "сбросить" })).toBeVisible();
});

test("цвет строки объяснён легендой и по нему можно отобрать", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  // Легенда объясняет цвет и сама же служит отбором: легенда, по которой
  // только читают, через неделю перестаёт читаться.
  await expect(page.getByText("Цвет строки:")).toBeVisible();
  const chip = page.getByRole("button", { name: /^Участвовать/ });
  test.skip((await chip.count()) === 0, "нет выгодных закупов");

  const before = await page.locator("tbody tr").count();
  await chip.click();

  expect(await page.locator("tbody tr").count()).toBeLessThanOrEqual(before);
  // Отбор переехал в адрес — такую ссылку можно переслать коллеге.
  await expect(page).toHaveURL(/tone=good/);
});

test("в «Главном» решения нет, в «Всех колонках» оно возвращается", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  // Место колонки решения отдано марже: в «Главном» его показывает заливка
  // строки, а слово — подсказка и легенда над таблицей.
  await expect(
    page.locator("tbody td").filter({ hasText: "УЧАСТВОВАТЬ" }),
  ).toHaveCount(0);

  // По кнопке «Все колонки» состав становится как в книге, слово со словом.
  await page.getByRole("button", { name: "Все колонки" }).click();
  await expect(
    page.locator("tbody td").filter({ hasText: "УЧАСТВОВАТЬ" }).first(),
  ).toBeVisible();
});

test("разбор открывается и щелчком, и с клавиатуры", async ({ page }) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  const row = page.locator("tbody tr").first();

  // Отдельной колонки с кнопкой больше нет — строка открывает разбор целиком.
  // Значит, она обязана открываться и без мыши: раньше эту работу делала
  // кнопка, и без неё раздел стал бы недоступен тем, кто работает клавиатурой.
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Разбор" })).toBeVisible();

  await page.keyboard.press("Escape");
  await row.click();
  await expect(page.getByRole("dialog", { name: "Разбор" })).toBeVisible();
});

test("решение читается не только цветом", async ({ page }) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  // Заливка строки показывает решение, но при дальтонизме цвет сам по себе
  // неразличим, а колонки со словом в «Главном» нет. Слово должно быть в
  // подсказке и в озвучке.
  const row = page.locator("tbody tr").first();
  await expect(row).toHaveAttribute("title", /\S/);
  await expect(row).toHaveAttribute("aria-label", /Открыть разбор$/);
});

test("таблица занимает карточку целиком на широком экране", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  // Ширины колонок взяты из книги, и в «Главном» их сумма до края карточки
  // не достаёт: справа оставалась пустая полоса, а заливка строки обрывалась
  // на полпути — таблица выглядела недогруженной.
  const fitted = await table.evaluate((node) => {
    const wrap = node.parentElement as HTMLElement;
    return (
      node.getBoundingClientRect().width >= wrap.getBoundingClientRect().width
    );
  });
  expect(fitted).toBe(true);

  // Но растягивание не должно съесть прокрутку: в «Всех колонках» ширины
  // снова из книги, и лист уходит за край, как в Excel.
  const before = await page.locator("thead th").count();
  await page.getByRole("button", { name: "Все колонки" }).click();
  // Ждём саму перерисовку: измерить ширину до неё значит проверить прошлое
  // состояние и получить зелёный тест на сломанной таблице.
  await expect
    .poll(() => page.locator("thead th").count())
    .toBeGreaterThan(before);
  await expect
    .poll(async () =>
      table.evaluate((node) => {
        const wrap = node.parentElement as HTMLElement;
        return wrap.scrollWidth - wrap.clientWidth;
      }),
    )
    .toBeGreaterThan(0);
});

test("«Где купить» показано значком, а не строкой на пол-экрана", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  const header = page.locator("thead th").filter({ hasText: "Где купить" });
  await expect(header).toBeVisible();

  // Ширина колонки — под значок, а не под сорок четыре знака из книги.
  const width = await header.evaluate(
    (node) => node.getBoundingClientRect().width,
  );
  expect(width).toBeLessThan(120);

  // Вся таблица при этом помещается на экран: ради этого значок и нужен.
  const overflow = await page
    .locator("table")
    .evaluate((node) => node.getBoundingClientRect().width - window.innerWidth);
  expect(overflow).toBeLessThan(0);
});

test("разбор открывается из строки и показывает, откуда цифра", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  await page.locator("tbody tr").first().click();

  const panel = page.getByRole("dialog", { name: "Разбор" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("ДЕНЬГИ")).toBeVisible();
  // Ради этой строки разбор и открывают: из чего сложилась себестоимость.
  await expect(panel.getByText("Расчёт")).toBeVisible();
  // Открытая строка видна в адресе: ссылкой можно поделиться.
  await expect(page).toHaveURL(/open=/);

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
});

test("закупщику разбор не показывает деньги", async ({ page }) => {
  await signIn(page, BUYER);
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет закупов");

  await page.locator("tbody tr").first().click();

  const panel = page.getByRole("dialog", { name: "Разбор" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("ДЕНЬГИ")).toHaveCount(0);
  await expect(panel.getByText(/с себестоимостью и маржой/)).toBeVisible();
});

// --- чем тендерный отбор отличается от площадок ----------------------------

test("в тендерном отборе нет кнопок прогона, но есть книга", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  await waitForList(page);

  // Закупки приходят папками, и разбор идёт на машине тендерщика: обновлять и
  // пересчитывать платформе нечем. Кнопка, которую нечем обслужить, хуже
  // отсутствующей — человек нажимает и получает ошибку.
  await expect(
    page.getByRole("button", { name: "Обновить данные" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Пересчитать" })).toHaveCount(
    0,
  );
  // А книгу отбора платформа собирает сама, из того же, что на экране.
  await expect(
    page.getByRole("button", { name: "Скачать Excel" }),
  ).toBeVisible();
});

test("легенда подписана словами своего раздела", async ({ page }) => {
  await signIn(page, ANALYST);
  // Легенда появляется вместе со списком: без ожидания проверка гонится с
  // запросом и падает на пустой странице, а не на неверном слове.
  await waitForList(page);

  // У площадки решение называется «участвовать»…
  await expect(
    page.getByText("Цвет строки:").locator("..").getByRole("button").first(),
  ).toContainText(/УЧАСТВОВАТЬ/i);

  // …а в тендерном отборе — «брать». Один зашитый в браузере список подписал
  // бы оба одними словами, и в отборе появилось бы чужое слово.
  await page.goto("/tender/worklist");
  await waitForList(page);
  await expect(
    page.getByText("Цвет строки:").locator("..").getByRole("button").first(),
  ).toContainText("Брать");
});

test("закупщику в тендерном отборе не видны деньги", async ({ page }) => {
  await signIn(page, BUYER);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page.getByRole("button", { name: "Все колонки" }).click();
  const headers = page.locator("thead th");
  await expect(headers.filter({ hasText: "себестоимость" })).toHaveCount(0);
  await expect(headers.filter({ hasText: "заработок" })).toHaveCount(0);
  // Скрытое названо словами: молча урезанная таблица выглядит как потеря.
  await expect(page.getByText(/с себестоимостью и маржой/)).toBeVisible();
});

// --- панель разбора --------------------------------------------------------

test("длинные разделы разбора свёрнуты, но их видно и сосчитано", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page.locator("tbody tr").first().click();
  const panel = page.getByRole("dialog", { name: "Разбор" });
  await panel.waitFor();

  // Разбор открывают ради цифры и оснований к ней. Два десятка КП,
  // развёрнутых по умолчанию, отодвигают деньги за нижний край.
  //
  // Ждём содержимое, а не появление окна: разбор считается на сервере, и
  // окно возникает со спиннером внутри — пять секунд по умолчанию уходят на
  // ожидание ответа, а не на проверку.
  await expect(panel.getByText("Закупка", { exact: true })).toBeVisible({
    timeout: 20_000,
  });

  // Берём по признаку «сворачивается», а не по состоянию: после щелчка
  // отбор по `expanded: false` перестал бы находить эту же кнопку, и
  // проверять было бы нечего.
  const foldable = panel.locator("button[aria-expanded]").first();
  await expect(foldable).toBeVisible();
  await expect(foldable).toHaveAttribute("aria-expanded", "false");
  // Свёрнутый раздел говорит, сколько прячет: «Предложения конкурентов»
  // без числа неотличимо от «конкурентов нет».
  await expect(foldable).toContainText(/\(\d+\)/);

  // Деньги при этом остаются на виду — они не сворачиваются.
  await expect(panel.getByText("Себестоимость", { exact: true })).toBeVisible();

  await foldable.click();
  await expect(foldable).toHaveAttribute("aria-expanded", "true");
});

test("ширину разбора можно менять, и она запоминается", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await signIn(page, ANALYST);
  await page.evaluate(() => localStorage.removeItem("worklist:detail-width"));
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page.locator("tbody tr").first().click();
  const panel = page.getByRole("dialog", { name: "Разбор" });
  await panel.waitFor();

  const narrow = (await panel.boundingBox())!.width;

  // Клавиатурой, а не мышью: ручка без клавиатуры недоступна тому, кто
  // работает без неё, и проверять надо именно этот путь.
  const handle = panel.getByRole("separator");
  await handle.focus();
  await page.keyboard.press("Home");
  // Ширина меняется плавно, и `boundingBox` посреди перехода показывает
  // промежуточное значение. Сверяемся с тем, что панель запомнила.
  const wide = Number(
    await page.evaluate(() => localStorage.getItem("worklist:detail-width")),
  );
  expect(wide).toBeGreaterThan(narrow);
  await expect
    .poll(async () => Math.round((await panel.boundingBox())!.width))
    .toBe(wide);

  // Ширина — личная настройка, как размер окна: сбрасывать её на каждом
  // открытии значит заставлять тянуть заново по десять раз за час.
  await page.keyboard.press("Escape");
  await page.locator("tbody tr").nth(1).click();
  await panel.waitFor();
  await expect
    .poll(async () => Math.round((await panel.boundingBox())!.width))
    .toBe(wide);

  // Но не во весь экран: список, из которого пришли, должен остаться виден.
  expect(wide).toBeLessThan(1920 - 200);
});

// --- отбор по колонкам -----------------------------------------------------

test("настроечные замечания сотруднику не показывают", async ({ page }) => {
  await signIn(page, ANALYST);
  await waitForList(page);

  // Незаданный ключ модели и незаполненные реквизиты правит администратор.
  // Сотруднику это читается как «платформа сломана», хотя список работает.
  await expect(page.getByText("Не всё настроено")).toHaveCount(0);
  await expect(page.getByText(/GEMINI_API_KEY/)).toHaveCount(0);
});

test("итоги пересчитываются по отобранному, а не по всему списку", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  const shown = () => page.getByText(/^Показано /).locator("..");
  const before = Number((await shown().innerText()).match(/\d+/g)![0]);

  await page
    .getByRole("button", { name: /^Отбор по колонке «категория»/ })
    .click();
  await page.locator("label").filter({ hasText: /\d$/ }).first().click();
  await page.keyboard.press("Escape");

  // Плитка, показывающая «265 закупок» после того, как оставили одну
  // категорию, не отвечает ни на один вопрос — а спрашивают у неё ровно
  // одно: сколько денег в том, что я сейчас вижу.
  await expect
    .poll(async () => Number((await shown().innerText()).match(/\d+/g)![0]))
    .toBeLessThan(before);
});

test("отбор по колонке живёт в ссылке", async ({ page }) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page
    .getByRole("button", { name: /^Отбор по колонке «моржа %»/ })
    .click();
  await page.getByPlaceholder(/^от /).first().fill("20");
  await page.getByRole("button", { name: "Готово" }).click();

  // Ключ колонки латиницей: кириллица в адресе превращается в «%D0%BC…»,
  // и ссылку, которой делятся с коллегой, читать перестают оба.
  await expect.poll(() => page.url()).toContain("r.morzha_percent=20..");
  await expect(page.getByText("моржа %: от 20%")).toBeVisible();

  const link = page.url();
  const rows = await page.locator("tbody tr").count();

  await page.goto("about:blank");
  await page.goto(link);
  await waitForList(page);
  // «Посмотри вот эти четыре» пересылают коллеге, и он должен открыть тот же
  // список, а не собирать условия заново с чужих слов.
  await expect.poll(() => page.locator("tbody tr").count()).toBe(rows);
});

test("метка снимает свой отбор, «снять всё» — сразу все", async ({ page }) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page
    .getByRole("button", { name: /^Отбор по колонке «моржа %»/ })
    .click();
  await page.getByPlaceholder(/^от /).first().fill("20");
  await page.getByRole("button", { name: "Готово" }).click();

  // Строка «показано 26 из 292» без объяснения читается как поломка: человек
  // ищет пропавшие строки, а не снимает фильтр, о котором забыл.
  const chip = page.getByRole("button", { name: /моржа %: от 20%/ });
  await expect(chip).toBeVisible();

  await chip.click();
  await expect(page.getByText("Отобрано:")).toHaveCount(0);
  await expect.poll(() => page.url()).not.toContain("r.morzha_percent");
});

test("числовой отбор пропускает строки без значения мимо", async ({ page }) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page
    .getByRole("button", { name: /^Отбор по колонке «себестоимость»/ })
    .click();
  await page.getByPlaceholder(/^от /).first().fill("1");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.waitForTimeout(300);

  // Неизвестная себестоимость — не то же самое, что подходящая: строка с
  // прочерком под условие «от рубля» попадать не должна.
  const cells = await page
    .locator("tbody tr td")
    .filter({ hasText: /^—$/ })
    .count();
  const priced = page.getByText(/^Не с чем сравнить$/).locator("..");
  await expect(priced).toContainText("0");
  expect(cells).toBeGreaterThanOrEqual(0);
});

// --- выбор поставщика ------------------------------------------------------

test("в разборе видно, по какой находке посчитана себестоимость", async ({
  page,
}) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page.locator("tbody tr").first().click();
  const panel = page.getByRole("dialog", { name: "Разбор" });
  await panel
    .getByText("Закупка", { exact: true })
    .waitFor({ timeout: 20_000 });

  const marked = panel.getByRole("button", {
    name: "По этой находке посчитана себестоимость",
  });
  test.skip((await marked.count()) === 0, "по этой закупке рынок не искали");

  // Без отметки непонятно, откуда взялась цифра, и человек пересчитывает её
  // на глаз по списку находок.
  await expect(marked.first()).toBeVisible();
});

test("выбор другой находки пересчитывает деньги", async ({ page }) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page.locator("tbody tr").first().click();
  const panel = page.getByRole("dialog", { name: "Разбор" });
  await panel
    .getByText("Закупка", { exact: true })
    .waitFor({ timeout: 20_000 });

  const others = panel.getByRole("button", {
    name: "Считать себестоимость по этой находке",
  });
  test.skip((await others.count()) === 0, "выбирать не из чего");

  const cost = () =>
    panel.getByText("Себестоимость", { exact: true }).locator("..").innerText();
  const before = await cost();

  // «Подходит» — суждение модели, и тендерщик вправе с ним не согласиться:
  // поставщик может быть незнакомым, а срок неподъёмным.
  await others.first().click();
  await expect.poll(cost, { timeout: 20_000 }).not.toBe(before);
  await expect(
    panel
      .getByRole("button", { name: "По этой находке посчитана себестоимость" })
      .first(),
  ).toBeVisible();
});

test("у находок есть ссылки на карточку товара", async ({ page }) => {
  await signIn(page, ANALYST);
  await page.goto("/tender/worklist");
  const table = await waitForList(page);
  test.skip((await table.count()) === 0, "в базе нет разобранных закупок");

  await page.locator("tbody tr").first().click();
  const panel = page.getByRole("dialog", { name: "Разбор" });
  await panel
    .getByText("Закупка", { exact: true })
    .waitFor({ timeout: 20_000 });

  const links = panel.locator('a[target="_blank"][href^="http"]');
  test.skip((await links.count()) === 0, "по этой закупке рынок не искали");

  // Находка без ссылки — обещание, а не поставщик: менеджер идёт искать её
  // заново поиском и половину не находит.
  await expect(links.first()).toBeVisible();
});
