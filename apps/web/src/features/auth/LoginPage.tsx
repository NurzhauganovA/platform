/**
 * Вход.
 *
 * Сообщение об ошибке приходит с сервера и одинаково на все причины отказа.
 * Уточнять его здесь нельзя: «нет такого пользователя» против «неверный
 * пароль» превращает форму в способ узнать, кто в компании работает, — а по
 * адресам сотрудников строят фишинг.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { auth } from "@/api/tender";
import { ApiError } from "@/api/client";
import { Button, Card, Field, Input } from "@/ui";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [forgot, setForgot] = useState(false);
  const navigate = useNavigate();
  const client = useQueryClient();

  const login = useMutation({
    mutationFn: () => auth.login(email, password),
    onSuccess: (me) => {
      client.setQueryData(["me"], me);
      // На корень, а не на угаданный раздел. Прежний адрес вёл на
      // `/tender/cases` — маршрута с таким именем давно нет, и человек
      // попадал на запасной `/skstore/bargains`, который юристу и технологу
      // закрыт. Куда идти, решает корень: он знает роль и меню.
      navigate("/", { replace: true });
    },
  });

  const error =
    login.error instanceof ApiError
      ? login.error.message
      : login.error
        ? "Не удалось войти"
        : null;

  if (forgot) {
    return <Forgot email={email} onBack={() => setForgot(false)} />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-plane px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-xl font-semibold tracking-tight text-ink">
            Fintend
          </div>
          <p className="mt-1 text-sm text-ink-muted">Закупки и тендеры</p>
        </div>

        <Card className="px-6 py-6">
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              login.mutate();
            }}
          >
            <Field label="Почта">
              <Input
                type="email"
                value={email}
                autoComplete="username"
                autoFocus
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@fintend.kz"
                required
              />
            </Field>

            <Field label="Пароль">
              <Input
                type="password"
                value={password}
                autoComplete="current-password"
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </Field>

            {error && (
              <p
                role="alert"
                className="rounded-[8px] border border-critical/40 bg-critical/10 px-3 py-2 text-sm text-critical"
              >
                {error}
              </p>
            )}

            <Button
              type="submit"
              variant="primary"
              disabled={login.isPending}
              className="w-full"
            >
              {login.isPending ? "Проверяем…" : "Войти"}
            </Button>

            <button
              type="button"
              onClick={() => setForgot(true)}
              className="w-full text-center text-xs text-ink-muted transition hover:text-ink"
            >
              Забыли пароль?
            </button>
          </form>
        </Card>

        <p className="mt-4 text-center text-xs text-ink-muted">
          Учётные записи заводит администратор — открытой регистрации нет.
        </p>
      </div>
    </div>
  );
}

/**
 * Смена забытого пароля кодом.
 *
 * Кодом, а не ссылкой в письме. Ссылку можно переслать, и она не работает в
 * Телеграме — а туда код и уходит у тех, кто привязал чат. Шесть цифр
 * называют вслух и вводят руками.
 *
 * Два шага на одном экране: попросить код и ввести его. Отдельная страница для
 * второго шага означала бы, что человек, закрывший вкладку, начинает заново, —
 * а закрывает он её как раз чтобы посмотреть код.
 *
 * Ответ одинаков на известный и неизвестный адрес. Разные превратили бы форму
 * в способ проверять, работает ли у нас такой-то человек: адреса сотрудников
 * есть у каждого заказчика, которому мы писали.
 */
function Forgot({
  email: known,
  onBack,
}: {
  email: string;
  onBack: () => void;
}) {
  const [email, setEmail] = useState(known);
  const [code, setCode] = useState("");
  const [fresh, setFresh] = useState("");
  const [sent, setSent] = useState(false);
  const [channel, setChannel] = useState("");
  const [done, setDone] = useState(false);
  const [trouble, setTrouble] = useState("");

  const ask = useMutation({
    mutationFn: () => auth.askReset(email),
    onSuccess: (answer) => {
      setTrouble("");
      setChannel(answer.channel);
      setSent(true);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const put = useMutation({
    mutationFn: () => auth.resetPassword(email, code, fresh),
    onSuccess: () => {
      setTrouble("");
      setDone(true);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-plane px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-xl font-semibold tracking-tight text-ink">
            Fintend
          </div>
          <p className="mt-1 text-sm text-ink-muted">Смена пароля</p>
        </div>

        <Card className="px-6 py-6">
          {done ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-ink">
                Пароль изменён. Вход на всех устройствах сброшен.
              </p>
              <Button variant="primary" className="w-full" onClick={onBack}>
                Войти
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <Field label="Рабочая почта">
                <Input
                  type="email"
                  value={email}
                  autoComplete="username"
                  autoFocus
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@fintend.kz"
                  readOnly={sent}
                />
              </Field>

              {!sent ? (
                <Button
                  variant="primary"
                  className="w-full"
                  onClick={() => ask.mutate()}
                  disabled={!email.includes("@") || ask.isPending}
                >
                  {ask.isPending ? "Отправляем…" : "Прислать код"}
                </Button>
              ) : (
                <>
                  <p className="rounded-[8px] border border-hairline bg-plane px-3 py-2 text-xs text-ink-secondary">
                    {channel === "telegram"
                      ? "Код отправлен в Телеграм. Он действует пятнадцать минут."
                      : "Если такой адрес у нас есть, код придёт на почту. Он действует пятнадцать минут."}
                  </p>

                  <Field label="Код из шести цифр">
                    <Input
                      value={code}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      onChange={(event) => setCode(event.target.value)}
                      placeholder="000000"
                    />
                  </Field>

                  <Field label="Новый пароль">
                    <Input
                      type="password"
                      value={fresh}
                      autoComplete="new-password"
                      onChange={(event) => setFresh(event.target.value)}
                    />
                  </Field>

                  <Button
                    variant="primary"
                    className="w-full"
                    onClick={() => put.mutate()}
                    disabled={code.length < 4 || !fresh || put.isPending}
                  >
                    {put.isPending ? "Меняем…" : "Сменить пароль"}
                  </Button>
                </>
              )}

              {trouble && (
                <p
                  role="alert"
                  className="rounded-[8px] border border-critical/40 bg-critical/10 px-3 py-2 text-sm text-critical"
                >
                  {trouble}
                </p>
              )}

              <button
                type="button"
                onClick={onBack}
                className="w-full text-center text-xs text-ink-muted transition hover:text-ink"
              >
                ← Ко входу
              </button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
