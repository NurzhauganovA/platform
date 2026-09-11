/**
 * Правая колонка карточки: ход лота рельсой и короткая карточка людей.
 *
 * Справа отдельным столбцом. Внизу длинной страницы действия не найти, а
 * вверху они зовут нажать раньше, чем прочитано согласование.
 *
 * Подписи здесь нет намеренно. Короткий вызов «ждут вашу подпись» дублировал
 * полосу согласования внизу: одно и то же действие двумя кнопками на одном
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
import { Card as Panel, cx } from "@/ui";
import { Steps } from "./Steps";
import { Avatar, shortName } from "./kit";

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
    /* Ширина колонки задаётся сеткой экрана, а не здесь: своя ширина у рельсы
       оставляла справа полосу фона в полсантиметра — она читалась как поле
       ещё одного, пустого блока. */
    <div className="space-y-2.5">
      {/* Свод задач ушёл в рельсу: он был числом по трём отделам, а рельса
          показывает ход целиком, и два свода на одном экране расходятся. */}
      <Steps card={card} people={people} onDone={onDone} />
      <People card={card} people={people} onDone={onDone} />
    </div>
  );
}

/**
 * Кто ведёт лот и идём ли мы на эту закупку.
 *
 * Двумя строками, а не блоком с подписями и кнопками. Менять ответственного и
 * решать об участии — действия редкие: первое раз за этап, второе раз за лот.
 * Развёрнутый блок под них занимал треть колонки, в которой всё остальное —
 * то, на что смотрят постоянно.
 *
 * Менеджер и текущий ответственный — разные роли: менеджер отвечает за закупку
 * целиком, ответственный за то, что с ней делают сейчас, и меняется от этапа к
 * этапу. Поэтому строки две, а не одна.
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
    <Panel className="overflow-hidden">
      <Kv label="Ведёт лот">
        <Who
          name={card.owner}
          value={card.owner_id}
          people={people}
          may={may && !assign.isPending}
          onChange={(id) =>
            assign.mutate({ owner_id: id || null, change_owner: true })
          }
        />
      </Kv>

      <Kv label="Менеджер">
        <Who
          name={card.manager}
          value={card.manager_id}
          people={people}
          may={may && !assign.isPending}
          onChange={(id) =>
            assign.mutate({ manager_id: id || null, change_manager: true })
          }
        />
      </Kv>

      {decides && (
        <Kv label="Участвуем?">
          {/* Двумя кнопками в одной рамке, а не переключателем: у решения три
              состояния — «да», «нет» и «ещё не решали», — и ползунок третьего
              показать не умеет. */}
          <span className="inline-flex overflow-hidden rounded-[8px] border border-hairline">
            <button
              type="button"
              onClick={() => decide.mutate(true)}
              disabled={decide.isPending}
              aria-pressed={card.participation === "yes"}
              className={cx(
                "h-[29px] px-3 text-[12.5px] transition",
                card.participation === "yes"
                  ? "bg-good font-medium text-white"
                  : "bg-surface text-ink-secondary hover:bg-plane",
              )}
            >
              Да
            </button>
            <button
              type="button"
              onClick={() => decide.mutate(false)}
              disabled={decide.isPending}
              aria-pressed={card.participation === "no"}
              className={cx(
                "h-[29px] border-l border-hairline px-3 text-[12.5px] transition",
                card.participation === "no"
                  ? "bg-ink-secondary font-medium text-surface"
                  : "bg-surface text-ink-secondary hover:bg-plane",
              )}
            >
              Нет
            </button>
          </span>
        </Kv>
      )}

      {card.participation === "no" && card.skip_reason && (
        <p className="px-[13px] py-2.5 text-[11.5px] text-ink-muted">
          Не участвуем: {card.skip_reason}
        </p>
      )}
      {trouble && (
        <p className="px-[13px] py-2.5 text-[12.5px] text-critical">
          {trouble}
        </p>
      )}
    </Panel>
  );
}

/** Строка «подпись — значение». Подпись слева мелким, значение справа. */
function Kv({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2.5 border-b border-hairline/70 px-[13px] py-2.5 last:border-b-0">
      <span className="shrink-0 text-[11.5px] text-ink-muted">{label}</span>
      {children}
    </div>
  );
}

/**
 * Человек в строке: кружок с инициалами и имя.
 *
 * Кому можно менять — тому список поверх имени. Рамки у списка нет, пока на
 * него не навели: три обведённых поля подряд в колонке выглядят формой,
 * которую надо заполнить, а заполнять тут нечего — это ответ на вопрос «кто».
 */
function Who({
  name,
  value,
  people,
  may,
  onChange,
}: {
  name: string;
  value: string;
  people: Person[];
  may: boolean;
  onChange: (id: string) => void;
}) {
  if (!may) {
    return name ? (
      <span className="flex min-w-0 items-center gap-1.5 text-[13px] text-ink">
        <Avatar name={name} />
        <span className="truncate">{shortName(name)}</span>
      </span>
    ) : (
      <span className="text-[12.5px] text-ink-muted">никого</span>
    );
  }

  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {name && <Avatar name={name} />}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label="Кто ведёт"
        className={cx(
          "min-w-0 max-w-[190px] truncate rounded-[7px] border border-transparent bg-transparent",
          "py-0.5 pr-1 pl-1 text-[13px] text-ink transition",
          "hover:border-hairline hover:bg-plane focus:border-series-1 focus:outline-none",
        )}
      >
        <option value="">никого</option>
        {people.map((person) => (
          <option key={person.id} value={person.id}>
            {person.name}
          </option>
        ))}
      </select>
    </span>
  );
}
