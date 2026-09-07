/**
 * Правая колонка карточки: шаги лота со своими сроками, задачами и людьми.
 *
 * Справа отдельным столбцом. Внизу длинной страницы действия не найти, а
 * вверху они зовут нажать раньше, чем прочитано согласование.
 *
 * Подписи здесь нет намеренно. Короткий вызов «ждут вашу подпись» дублировал
 * блок «Согласование» внизу: одно и то же действие двумя кнопками на одном
 * экране читается как два разных, и человек ищет разницу там, где её нет.
 *
 * Колонка не сворачивается. Кнопка со стрелкой стояла отдельной строкой над
 * блоками и сдвигала их вниз относительно состояния лота слева — две шапки на
 * одной высоте расходились на полтора сантиметра. Сворачивали её при этом
 * единицы: колонка отвечает на «что с лотом сейчас», и убирать её с экрана
 * незачем.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { cardsApi, type Card, type Person } from "@/api/cards";
import { ApiError } from "@/api/client";
import { Button, Card as Panel, cx } from "@/ui";
import { Queue } from "./Queue";
import { Steps } from "./Steps";

export function Rail({
  card,
  people,
  onDone,
}: {
  card: Card;
  people: Person[];
  onDone: (fresh: Card) => void;
}) {
  return (
    <aside className="sticky top-4 w-76 space-y-3">
      <Queue card={card} people={people} />
      <Steps card={card} people={people} onDone={onDone} />
      <People card={card} people={people} onDone={onDone} />
    </aside>
  );
}

/**
 * Кто ведёт лот.
 *
 * Менеджер и текущий ответственный — разные роли. Менеджер отвечает за
 * закупку целиком, ответственный — за то, что с ней делают сейчас, и меняется
 * от этапа к этапу.
 */
function People({
  card,
  people,
  onDone,
}: {
  card: Card;
  people: Person[];
  onDone: (fresh: Card) => void;
}) {
  const [trouble, setTrouble] = useState("");

  const assign = useMutation({
    mutationFn: (body: Parameters<typeof cardsApi.assign>[1]) =>
      cardsApi.assign(card.id, body),
    onSuccess: onDone,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const decide = useMutation({
    mutationFn: (yes: boolean) =>
      cardsApi.decide(
        card.id,
        yes ? "yes" : "no",
        yes ? "" : "решили не брать",
      ),
    onSuccess: onDone,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const may = card.can.includes("assign");
  const decides = card.can.includes("decide");

  return (
    <Panel title="Сотрудники">
      <div className="space-y-3 px-4 py-3">
        <Pick
          label="Менеджер поставки"
          value={card.manager_id}
          people={people}
          disabled={!may || assign.isPending}
          onChange={(id) =>
            assign.mutate({ manager_id: id || null, change_manager: true })
          }
        />
        <Pick
          label="Сейчас у кого"
          value={card.owner_id}
          people={people}
          disabled={!may || assign.isPending}
          onChange={(id) =>
            assign.mutate({ owner_id: id || null, change_owner: true })
          }
        />

        {decides && (
          <div>
            <p className="mb-1.5 text-xs text-ink-muted">Решение об участии</p>
            <div className="flex gap-2">
              <Button
                variant={card.participation === "yes" ? "primary" : "secondary"}
                onClick={() => decide.mutate(true)}
                disabled={decide.isPending}
              >
                Участвуем
              </Button>
              <Button
                variant={card.participation === "no" ? "danger" : "secondary"}
                onClick={() => decide.mutate(false)}
                disabled={decide.isPending}
              >
                Не участвуем
              </Button>
            </div>
          </div>
        )}

        {card.participation === "no" && card.skip_reason && (
          <p className="text-xs text-ink-muted">
            Не участвуем: {card.skip_reason}
          </p>
        )}
        {trouble && <p className="text-sm text-critical">{trouble}</p>}
      </div>
    </Panel>
  );
}

function Pick({
  label,
  value,
  people,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  people: Person[];
  disabled: boolean;
  onChange: (id: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-ink-muted">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={cx(
          "w-full rounded-[8px] border border-baseline bg-surface px-2.5 py-1.5",
          "text-sm text-ink focus:border-series-1 focus:outline-none",
          "disabled:cursor-not-allowed disabled:bg-plane disabled:text-ink-muted",
        )}
      >
        <option value="">никого</option>
        {people.map((person) => (
          <option key={person.id} value={person.id}>
            {person.name}
          </option>
        ))}
      </select>
    </label>
  );
}
