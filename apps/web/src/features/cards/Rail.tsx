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
import { useMutation, useQuery } from "@tanstack/react-query";
import { auth } from "@/api/tender";
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
 * Кто по лоту от каждого отдела и идём ли мы на эту закупку.
 *
 * Пять строк, по отделу в каждой: на планёрке спрашивают не «чей лот», а «кто
 * по нему юрист», и до сих пор ответом было открывание задач по одной.
 *
 * Метка слева фиксированной ширины — имена сотрудников должны начинаться с
 * одного места. От подогнанной по содержимому «Поставка» и «Обсуждение»
 * разъезжались на десяток точек, и столбец переставал читаться сверху вниз.
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
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });
  const [trouble, setTrouble] = useState("");

  const assign = useMutation({
    mutationFn: (body: Parameters<typeof cardsApi.assign>[1]) =>
      cardsApi.assign(card.id, body),
    onSuccess: onDone,
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  return (
    <Panel className="overflow-hidden">
      {/* Пять отделов, у каждого своя строка. Вместо прежних «Ведёт лот» и
          «Менеджер», которые отвечали на вопрос «кто за это отвечает» одним
          именем на всю закупку: на планёрке спрашивают не «чей лот», а «кто
          по нему юрист».

          Кнопки «Беру» здесь нет намеренно. Она вставала второй строкой рядом
          с именем и ломала столбец, а делала то же самое, что и список: взять
          работу на себя — это выбрать себя в нём. Первым пунктом стоит «я», и
          до него не нужно искать себя среди тридцати имён. */}
      {card.seats.map((place) => (
        <Kv key={place.desk} label={place.title}>
          <span className="flex min-w-0 items-center gap-1.5">
            <Who
              name={place.name}
              value={place.user_id}
              people={people}
              me={me?.id}
              may={
                !assign.isPending &&
                (place.can.includes("assign") || place.can.includes("take"))
              }
              onChange={(id) =>
                assign.mutate({ desk: place.desk, user_id: id || null })
              }
            />
          </span>
        </Kv>
      ))}

      {/* Переключателя «Участвуем? Да/Нет» здесь больше нет. Он стоял в
          самом низу столбца и упирался в плавающую кнопку переписки — нажать
          его было делом удачи. А вопрос у него был тот же, что у перевода в
          «Завершённый»: закупка кончилась, и надо сказать чем. Теперь ответ
          спрашивается там, одним окном и с ценой, если заявку подавали. */}
      {card.participation === "no" && card.skip_reason && (
        <p className="border-t border-hairline/70 px-[13px] py-2.5 text-[11.5px] text-ink-muted">
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
    <div className="flex items-center gap-2 border-b border-hairline/70 px-[13px] py-2 last:border-b-0">
      {/* Ширина метки задана, а не подогнана по содержимому: «Поставка» и
          «Обсуждение» разной длины, и от плавающей метки имена сотрудников
          начинались бы в пяти разных местах — столбец читается сверху вниз,
          и глаз цепляется за каждую ступеньку. */}
      <span className="w-[86px] shrink-0 text-[11.5px] leading-tight text-ink-muted">
        {label}
      </span>
      <span className="flex min-w-0 flex-1 items-center justify-end">
        {children}
      </span>
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
  me,
  onChange,
}: {
  name: string;
  value: string;
  people: Person[];
  may: boolean;
  /** Кто смотрит. Идёт первым пунктом списка — «взять на себя» это и есть
   *  выбрать себя, и искать своё имя среди тридцати не нужно. */
  me?: string;
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
        {me && <option value={me}>я</option>}
        {people
          .filter((person) => person.id !== me)
          .map((person) => (
            <option key={person.id} value={person.id}>
              {person.name}
            </option>
          ))}
      </select>
    </span>
  );
}
