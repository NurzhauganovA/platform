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
import { cardsApi, type Card, type Choice, type Person } from "@/api/cards";
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

  // Причина отказа спрашивается до нажатия, а не подставляется строкой.
  // Раньше сюда уезжало «решили не брать» — через месяц на вопрос «почему
  // прошли мимо этой закупки» отвечала эта строка, то есть никто.
  const [why, setWhy] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");

  // Набор причин — тот же, что у вкладки «Завершённые»: запрос уже в кэше
  // страницы, второй раз по сети за ним никто не идёт.
  const { data: picks } = useQuery({
    queryKey: ["card-stages"],
    queryFn: cardsApi.stages,
    staleTime: Infinity,
  });

  // «Нет» закрывает лот с итогом, а не просто помечает решение: закупка, мимо
  // которой прошли, для нас кончилась, и держать её в работе значит каждое
  // утро открывать лот, чтобы убедиться, что там ничего нового.
  const finish = useMutation({
    mutationFn: (what: { outcome: string; reason: string }) =>
      cardsApi.finish(card.id, what.outcome, what.reason),
    onSuccess: (fresh) => {
      setWhy(null);
      setOutcome("");
      onDone(fresh);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  // «Да» — только решение: лот остаётся в работе, и объяснять тут нечего.
  // «Нет» идёт другим путём (`finish`): оно закупку закрывает.
  const decide = useMutation({
    mutationFn: () => cardsApi.decide(card.id, "yes", ""),
    onSuccess: (fresh) => {
      setWhy(null);
      setOutcome("");
      onDone(fresh);
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  const decides = card.can.includes("decide");

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

      {decides && (
        <Kv label="Участвуем?">
          {/* Двумя кнопками в одной рамке, а не переключателем: у решения три
              состояния — «да», «нет» и «ещё не решали», — и ползунок третьего
              показать не умеет. */}
          <span className="inline-flex overflow-hidden rounded-[8px] border border-hairline">
            <button
              type="button"
              onClick={() => {
                setWhy(null);
                setOutcome("");
                decide.mutate();
              }}
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
              onClick={() => {
                setWhy(card.skip_reason || "");
                setOutcome(card.outcome !== "none" ? card.outcome : "");
              }}
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

      {/* Почему не участвуем — спрашиваем до нажатия, а не после. Окно с
          вопросом поверх уже нажатой кнопки человек закрывает крестиком, и в
          истории остаётся отказ без причины.

          Готовые причины — те же, что у завершённых лотов, и это один и тот
          же ответ: «не участвуем» закрывает закупку, и через месяц её ищут по
          той причине, которую здесь выбрали. Свой список рядом означал бы два
          набора слов об одном, и в отчёте они не сошлись бы. */}
      {why !== null && (
        <div className="border-t border-hairline/70 px-[13px] py-2.5">
          <label className="mb-1.5 block text-[11.5px] text-ink-muted">
            Почему не участвуем
          </label>

          <div className="mb-1.5 flex flex-wrap gap-1">
            {(picks?.done ?? [])
              .filter((item) => item.needs_reason)
              .map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={outcome === item.key}
                  onClick={() => {
                    setOutcome(item.key);
                    // Слово сразу ложится в поле: его дописывают, а не
                    // заменяют — «Код ТРУ не подходит» само по себе ответ
                    // неполный, и человек тут же добавляет, чем именно.
                    // Написанное своими руками не затираем: нажатие по
                    // соседней причине не должно стирать абзац.
                    setWhy((был) =>
                      !был || isWord(picks?.done, был)
                        ? word(picks?.done, item.key)
                        : был,
                    );
                  }}
                  className={cx(
                    "rounded-[6px] border px-2 py-0.5 text-[11.5px] transition",
                    outcome === item.key
                      ? "border-ink bg-ink text-surface"
                      : "border-hairline text-ink-secondary hover:bg-plane",
                  )}
                >
                  {item.title}
                </button>
              ))}
          </div>

          <textarea
            value={why}
            onChange={(event) => setWhy(event.target.value)}
            rows={2}
            placeholder="Выберите причину выше или напишите свою"
            className={cx(
              "w-full resize-y rounded-[8px] border border-baseline bg-surface px-2 py-1.5",
              "text-[12.5px] leading-relaxed text-ink placeholder:text-ink-muted",
              "focus:border-series-1 focus:outline-none",
            )}
          />
          <div className="mt-1.5 flex gap-2">
            <button
              type="button"
              disabled={!why.trim() || finish.isPending}
              onClick={() =>
                finish.mutate({
                  // Ничего не выбрали, но написали своими словами — это
                  // «не участвуем»: решение наше, объяснение своё.
                  outcome: outcome || "skipped",
                  // Причина — что написали; не написали ничего, значит ею и
                  // служит выбранное слово. Пустой она быть не может: служба
                  // такой отказ не примет, и правильно.
                  reason: why.trim(),
                })
              }
              title={
                why.trim() || outcome
                  ? undefined
                  : "Выберите причину или напишите свою"
              }
              className={cx(
                "rounded-[7px] bg-ink px-2.5 py-1 text-[12px] font-medium text-surface",
                "transition disabled:opacity-40",
              )}
            >
              {finish.isPending ? "Сохраняем…" : "Не участвуем"}
            </button>
            <button
              type="button"
              onClick={() => {
                setWhy(null);
                setOutcome("");
              }}
              className="rounded-[7px] px-2 py-1 text-[12px] text-ink-secondary hover:bg-plane"
            >
              Отмена
            </button>
          </div>
        </div>
      )}

      {why === null && card.participation === "no" && card.skip_reason && (
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
/** Слово выбранной причины — им и объясняем отказ, если своими словами не
 *  написали. Пустой причины служба не примет, и правильно: через месяц на
 *  вопрос «почему прошли мимо» отвечать будет некому. */
function word(picks: Choice[] | undefined, key: string): string {
  return picks?.find((item) => item.key === key)?.title ?? "Не участвуем";
}

/** Стоит ли в поле ровно готовая причина и ничего больше. По этому и решаем,
 *  можно ли её заменить: дописанное человеком затирать нельзя. */
function isWord(picks: Choice[] | undefined, text: string): boolean {
  return (picks ?? []).some((item) => item.title === text.trim());
}

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
