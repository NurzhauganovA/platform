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
  const navigate = useNavigate();
  const client = useQueryClient();

  const login = useMutation({
    mutationFn: () => auth.login(email, password),
    onSuccess: (me) => {
      client.setQueryData(["me"], me);
      navigate("/tender/cases", { replace: true });
    },
  });

  const error =
    login.error instanceof ApiError ? login.error.message : login.error ? "Не удалось войти" : null;

  return (
    <div className="flex min-h-screen items-center justify-center bg-plane px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-xl font-semibold tracking-tight text-ink">Fintend</div>
          <p className="mt-1 text-sm text-ink-muted">Тендерный отдел</p>
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
          </form>
        </Card>

        <p className="mt-4 text-center text-xs text-ink-muted">
          Учётные записи заводит администратор — открытой регистрации нет.
        </p>
      </div>
    </div>
  );
}
