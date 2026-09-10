/**
 * Лоты в работе.
 *
 * Таблица, а не карточки. Лотов в работе бывает по сотне, у каждого срок в
 * часах; карточками это лента, по которой нельзя пробежать глазами колонку
 * сроков и увидеть, что горит.
 *
 * Вкладки идут по ходу лота, а не по алфавиту: список читают, чтобы понять,
 * что где застряло, и порядок вкладок — это и есть порядок процесса.
 *
 * Отбор идёт по уже полученным данным. Сотня строк лежит в памяти вкладки, и
 * второй запрос ради того, что в ней уже есть, — это полсекунды на нажатие.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { auth } from "@/api/tender";
import {
  cardsApi,
  FLOW,
  OFF_TRACK,
  type Card,
  type Job,
  type LotStatus,
  type Person,
} from "@/api/cards";
import { LotBoard } from "@/features/cards/LotBoard";
import { PageHeader } from "@/shell/AppShell";
import { PeopleFilter, type Load } from "@/ui/people";
import { FetchByNumber } from "./FetchByNumber";
import {
  Card as Panel,
  EmptyState,
  Page,
  Search,
  Spinner,
  Switch,
  Tabs,
  cx,
  money,
} from "@/ui";

type Tab = "burning" | "mine" | "unowned" | "all" | LotStatus;

const TABS: { key: Tab; title: string }[] = [
  { key: "burning", title: "Горит" },
  { key: "mine", title: "Мои" },
  { key: "unowned", title: "Ничьи" },
  { key: "discussion", title: "Обсуждение" },
  { key: "analysis", title: "Разбор" },
  { key: "approval", title: "Согласование" },
  { key: "ready", title: "Готовы" },
  { key: "awaiting", title: "Ждём итоги" },
  { key: "contract", title: "Договор" },
  { key: "all", title: "Все" },
];

/** Цвет полосы слева. Отмечает не важность, а место в процессе. */
const RULE: Record<LotStatus, string> = {
  new: "bg-baseline",
  discussion: "bg-series-5",
  analysis: "bg-series-1",
  approval: "bg-series-4",
  ready: "bg-series-3",
  awaiting: "bg-series-2",
  won: "bg-good",
  lost: "bg-hairline",
  contract: "bg-series-3",
  fulfilling: "bg-series-3",
  awaiting_payment: "bg-series-4",
  done: "bg-hairline",
  skipped: "bg-hairline",
  cancelled: "bg-hairline",
};

export function LotsPage() {
  // Вкладка не выбрана, пока человек её не выбрал. Зашитое «Горит» открывало
  // пустой экран в тот день, когда ничего не горит, — а это нормальный день:
  // список выглядел сломанным ровно тогда, когда всё в порядке.
  const [picked, setPicked] = useState<Tab | null>(null);
  const [search, setSearch] = useState("");

  // Таблица по умолчанию, доска — по выбору. Доской список читают те, кто
  // ведёт лоты сам; остальным нужна колонка сроков, по которой можно пробежать
  // глазами, и доска им мешала на входе. Вид всё так же живёт в адресе:
  // ссылку на доску отправляют коллеге, и открыться она должна доской.
  const [params, setParams] = useSearchParams();
  const board = params.get("vid") === "doska";
  const setBoard = (next: boolean) => {
    const now = new URLSearchParams(params);
    if (next) now.set("vid", "doska");
    else now.delete("vid");
    setParams(now, { replace: true });
  };

  // Чей список смотрим. Пусто — все. Это «Мои», но от третьего лица: вопрос
  // «сколько висит на Иванове» задают на планёрке каждый день.
  const [who, setWho] = useState("");

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });
  const { data, isLoading, error } = useQuery({
    queryKey: ["cards"],
    queryFn: () => cardsApi.list(),
    refetchInterval: 60_000,
  });
  const { data: people } = useQuery({
    queryKey: ["people"],
    queryFn: cardsApi.people,
    staleTime: 10 * 60 * 1000,
  });
  // Открытые задачи на всех лотах разом. Одним запросом на страницу, а не по
  // запросу на человека: тридцать сотрудников — это тридцать обращений ради
  // одного столбца чисел в выпадающем списке.
  const { data: jobs } = useQuery({
    queryKey: ["card-tasks", "open"],
    queryFn: () => cardsApi.tasks({ state: "open" }),
    staleTime: 60_000,
  });

  const all = useMemo(() => data ?? [], [data]);
  const counts = useMemo(() => countBy(all, me?.id), [all, me?.id]);
  const load = useMemo(
    () => loadOf(people ?? [], all, jobs ?? []),
    [people, all, jobs],
  );
  const tab = picked ?? opening(counts);

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return all.filter((item) => {
      // На доске состояние задают колонки, и вкладка по статусу спорила бы
      // с ними: выбранная «Разбор» оставила бы на доске одну колонку из
      // четырнадцати. Поиск и «Мои» работают на обоих видах.
      if (who && item.owner_id !== who && item.manager_id !== who) return false;
      if (!belongs(item, board ? scoped(tab) : tab, me?.id)) return false;
      if (!needle) return true;
      return `${item.code} ${item.title} ${item.customer} ${item.row_id}`
        .toLowerCase()
        .includes(needle);
    });
  }, [all, tab, search, me?.id, board, who]);

  return (
    <>
      <PageHeader
        title="Лоты в работе"
        subtitle="Сквозной путь закупки от объявления до оплаты"
        action={
          counts.burning > 0 ? (
            <span className="text-sm text-ink-secondary">
              горит{" "}
              <b className="font-semibold text-critical">{counts.burning}</b> из{" "}
              {all.length}
            </span>
          ) : (
            <span className="text-sm text-ink-muted">всего {all.length}</span>
          )
        }
      />

      <Page>
        {/* Выборка по номеру — над отбором, а не в нём: отбор сужает то, что
            уже есть, а это добавляет то, чего нет. */}
        <div className="flex flex-wrap items-start justify-between gap-3 rounded-[10px] border border-hairline bg-surface px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">Закупку пропустили?</p>
            <p className="mt-0.5 max-w-lg text-xs text-ink-muted">
              Введите код номер - заберём с портала строго по нему и возьмём в
              работу
            </p>
          </div>
          <FetchByNumber />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          {board ? (
            <Tabs
              tabs={SCOPES}
              value={scoped(tab)}
              counts={counts}
              onChange={setPicked}
              label="Чьи лоты"
            />
          ) : (
            <Tabs
              tabs={TABS}
              value={tab}
              counts={counts}
              onChange={setPicked}
            />
          )}

          <div className="flex items-center gap-2">
            <PeopleFilter
              people={load}
              value={who}
              onChange={setWho}
              total={all.length}
            />
            <Search
              value={search}
              onChange={setSearch}
              placeholder="Код, лот, заказчик"
            />
            <Switch
              value={board ? "doska" : "tablica"}
              onChange={(next) => setBoard(next === "doska")}
              options={[
                { value: "doska", title: "Доска" },
                { value: "tablica", title: "Таблица" },
              ]}
              label="Вид"
            />
          </div>
        </div>

        {isLoading ? (
          <Panel className="px-5 py-4">
            <Spinner label="Читаем лоты…" />
          </Panel>
        ) : error ? (
          <Panel>
            <EmptyState
              title="Список не открылся"
              description={
                error instanceof Error
                  ? error.message
                  : "Попробуйте обновить страницу"
              }
            />
          </Panel>
        ) : shown.length === 0 ? (
          <Panel>
            <EmptyState
              title={tab === "burning" ? "Ничего не горит" : "Здесь пусто"}
              description={
                tab === "burning"
                  ? "Все сроки пока с запасом. Соседние вкладки покажут остальное."
                  : "Лот берётся в работу кнопкой в рабочем списке площадки."
              }
            />
          </Panel>
        ) : board ? (
          <LotBoard lots={shown} />
        ) : (
          <Panel className="overflow-hidden">
            <Head />
            <ul>
              {shown.map((item) => (
                <Row key={item.id} card={item} />
              ))}
            </ul>
          </Panel>
        )}
      </Page>
    </>
  );
}

const GRID =
  "grid grid-cols-[3px_5.5rem_minmax(0,1fr)_8.5rem_6.5rem_9rem_5rem_7.5rem_5.5rem] items-center gap-x-4";

function Head() {
  return (
    <div
      className={cx(
        GRID,
        "border-b border-hairline bg-plane py-2 pr-5 pl-0",
        "text-xs font-medium tracking-wide text-ink-muted uppercase",
      )}
    >
      <span />
      <span>Код</span>
      <span>Закупка</span>
      <span className="text-right">Сумма, ₸</span>
      <span>Осталось</span>
      <span>Этап</span>
      <span className="text-center">Задачи</span>
      <span>Ведёт</span>
      <span
        className="text-center"
        title="Обсуждение · Разбор · Снабжение · Технолог"
      >
        Отделы
      </span>
    </div>
  );
}

function Row({ card }: { card: Card }) {
  const off = OFF_TRACK.includes(card.status);
  return (
    <li className="border-b border-hairline last:border-0">
      <Link
        to={`/work/lots/${card.id}`}
        className={cx(GRID, "py-2.5 pr-5 pl-0 transition hover:bg-plane")}
      >
        <span
          className={cx("h-8 w-[3px] rounded-r", RULE[card.status])}
          aria-hidden
        />

        <span className="font-mono text-xs text-ink-muted">{card.code}</span>

        <span className="min-w-0">
          <span
            className={cx(
              "block truncate text-sm",
              off ? "text-ink-muted" : "text-ink",
            )}
          >
            {card.title}
          </span>
          <span className="mt-0.5 block truncate text-xs text-ink-muted">
            {card.customer || card.row_id}
          </span>
        </span>

        <span className="text-right text-sm tabular-nums text-ink-secondary">
          {card.amount === null ? "—" : money(card.amount)}
        </span>

        <Deadline card={card} />

        <span className="min-w-0">
          <span
            className={cx(
              "block truncate text-sm",
              off ? "text-ink-muted" : "text-ink",
            )}
          >
            {card.status_name}
          </span>
          {card.step > 0 && (
            <span className="mt-0.5 block text-xs text-ink-muted tabular-nums">
              шаг {card.step} из {FLOW.length}
            </span>
          )}
        </span>

        <span className="text-center text-sm tabular-nums">
          {card.open_tasks > 0 ? (
            <span className="text-ink">{card.open_tasks}</span>
          ) : (
            <span className="text-ink-muted">—</span>
          )}
        </span>

        <span className="truncate text-sm">
          {card.owner ? (
            <span className="text-ink-secondary">{card.owner}</span>
          ) : (
            <span className="text-ink-muted">ничьё</span>
          )}
        </span>

        <Desks card={card} />
      </Link>
    </li>
  );
}

/**
 * Ход по отделам четырьмя точками: обсуждение, разбор, снабжение, технолог.
 *
 * Ради вопроса планёрки «что сейчас с этой закупкой». Ответ на него до сих пор
 * собирался открыванием карточки и разглядыванием правого столбца — по одному
 * лоту за раз, а на планёрке их тридцать. Этап в соседней колонке отвечает на
 * другое: он про то, где лот в пути, и молчит о том, что снабжение своё уже
 * сделало, а технолог ещё нет.
 *
 * Кто закончил, решает сервер (`card.desks`). Правила у отделов разные —
 * обсуждение закрывается отправкой замечания, разбор переходом этапа,
 * снабжение и технолог закрытыми задачами, — и второй набор этих правил в
 * браузере разошёлся бы с правым столбцом карточки на первом же.
 *
 * Галочка внутри кружка, а не цвет кружка. Зелёное и серое при дальтонизме
 * различаются плохо, а четыре точки подряд — это как раз тот случай, где
 * ошибиться легче всего. Подпись у каждой своя: без неё «третий кружок» надо
 * держать в голове.
 */
function Desks({ card }: { card: Card }) {
  const desks = card.desks ?? [];
  if (!desks.length) return <span aria-hidden />;

  return (
    <span className="flex items-center justify-center gap-1">
      {desks.map((desk) => (
        <span
          key={desk.desk}
          title={
            desk.done
              ? `${desk.title}: закончено`
              : desk.open_tasks > 0
                ? `${desk.title}: в работе, задач ${desk.open_tasks}`
                : `${desk.title}: ещё не начинали`
          }
          className={cx(
            "flex h-[18px] w-[18px] items-center justify-center rounded-full",
            "text-[10px] leading-none font-bold",
            desk.done
              ? "bg-good/15 text-good"
              : desk.open_tasks > 0
                ? "border border-series-1/50 text-series-1"
                : "border border-hairline text-ink-muted",
          )}
        >
          {desk.done ? "✓" : desk.open_tasks > 0 ? String(desk.open_tasks) : ""}
          <span className="sr-only">
            {desk.title}
            {desk.done ? " — закончено" : " — не закончено"}
          </span>
        </span>
      ))}
    </span>
  );
}

function Deadline({ card }: { card: Card }) {
  if (!card.left) {
    return <span className="text-sm text-ink-muted">—</span>;
  }
  if (card.overdue) {
    return (
      <span className="text-sm text-ink-muted line-through decoration-baseline">
        срок прошёл
      </span>
    );
  }
  return (
    <span
      className={cx(
        "text-sm tabular-nums whitespace-nowrap",
        card.burning ? "font-semibold text-critical" : "text-ink-secondary",
      )}
    >
      {card.left}
    </span>
  );
}

/**
 * «Горит» — то, что ещё можно успеть.
 *
 * Прошедший срок сюда не идёт. Вкладку открывают, чтобы понять, за что взяться
 * сейчас, а лот с истёкшим приёмом ни к какому действию не ведёт: он копился
 * в ней неделями и оттеснял вниз то, у чего срок и правда завтра. Никуда он не
 * девается — «Все» и вкладка его этапа показывают его по-прежнему.
 */
function belongs(item: Card, tab: Tab, me: string | undefined): boolean {
  if (tab === "all") return true;
  if (tab === "burning") return item.burning && !item.overdue;
  if (tab === "mine")
    return Boolean(me) && (item.owner_id === me || item.manager_id === me);
  if (tab === "unowned") return !item.owner_id;
  return item.status === tab;
}

/**
 * Сколько в каждой вкладке.
 *
 * Один проход на весь набор, а не по проходу на вкладку: десять проходов по
 * сотне строк на каждое нажатие — это заметная задержка там, где человек
 * просто переключает вид.
 */
/** Вкладки доски: состояние показывают колонки, остаётся «чьи». */
const SCOPES: { key: Tab; title: string }[] = [
  { key: "burning", title: "Горит" },
  { key: "mine", title: "Мои" },
  { key: "unowned", title: "Ничьи" },
  { key: "all", title: "Все" },
];

/** Вкладка по статусу на доске превратилась бы в одну колонку из четырнадцати. */
function scoped(tab: Tab): Tab {
  return SCOPES.some((item) => item.key === tab) ? tab : "all";
}

/**
 * На какой вкладке открыть список.
 *
 * По убыванию срочности: горящее важнее своего, своё важнее общего. Вкладку с
 * нулём не открываем — пустой список на входе человек читает как поломку и
 * идёт проверять, не отвалился ли сервер.
 */
function opening(counts: Record<Tab, number>): Tab {
  if (counts.burning) return "burning";
  if (counts.mine) return "mine";
  return "all";
}

/**
 * Сколько на каждом сотруднике.
 *
 * Лот считается своим и менеджеру, и текущему ответственному: вопрос «что на
 * нём» этих двух ролей не различает, и лот, который менеджер ведёт, а
 * разбирает другой, висит на обоих.
 */
function loadOf(people: Person[], all: Card[], jobs: Job[]): Load[] {
  return people.map((person) => ({
    id: person.id,
    name: person.name,
    rows: all.filter(
      (item) => item.owner_id === person.id || item.manager_id === person.id,
    ).length,
    tasks: jobs.filter((task) => task.assignee_id === person.id).length,
  }));
}

function countBy(all: Card[], me: string | undefined): Record<Tab, number> {
  const counts = { burning: 0, mine: 0, unowned: 0, all: all.length } as Record<
    Tab,
    number
  >;
  for (const item of all) {
    if (item.burning && !item.overdue) counts.burning += 1;
    if (me && (item.owner_id === me || item.manager_id === me))
      counts.mine += 1;
    if (!item.owner_id) counts.unowned += 1;
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  }
  return counts;
}
