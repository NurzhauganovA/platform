import { defineConfig } from "@playwright/test";

/**
 * Сквозные проверки.
 *
 * Идут против настоящего API и настоящей базы: то, что ломается на стыке —
 * кука сессии, поток прогресса, прокси, — в отдельных тестах слоёв не видно.
 * Поэтому серверы должны быть запущены; тесты их не поднимают, чтобы не
 * трогать рабочие данные без ведома человека.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://localhost:5173",
    locale: "ru-RU",
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
});
