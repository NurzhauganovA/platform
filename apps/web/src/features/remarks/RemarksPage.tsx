/**
 * Очередь обсуждений.
 *
 * Таблица, а не карточки. Замечаний в работе бывает по три десятка, у каждого
 * срок в часах; карточками это лента, по которой нельзя пробежать глазами
 * колонку сроков и увидеть, что горит. Строка отвечает на «успеваю ли», а не
 * пересказывает закупку.
 *
 * Один экран на все площадки: раздел здесь колонка. Сотрудник, который ведёт
 * замечания, ходит во все сразу, и три одинаковых списка заставили бы его
 * помнить, в каком он находится.
 *
 * Порядок задаёт сервер — по сроку, ближайший наверху. Пересортировать в
 * браузере значило бы завести второе правило о том, что срочно.
 *
 * Отбор идёт по уже полученным данным: список это десятки строк, а не
 * мегабайт, и второй запрос ради того, что лежит в памяти вкладки, — это
 * полсекунды ожидания на каждое нажатие.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { auth } from "@/api/tender";
import { cardsApi } from "@/api/cards";
import { remarks as api } from "@/api/remarks";
import type { Remark, Stage } from "@/api/remarks";
import { FilterBar, type Extra } from "./Filters";
import { PeopleFilter, type Load } from "@/ui/people";
import { PageHeader } from "@/shell/AppShell";
import {
  Card,
  EmptyState,
  Page,
  Search,
  Spinner,
  Switch,
  Tabs,
  cx,
  money,
} from "@/ui";
import { RemarkBoard } from "./RemarkBoard";
import {
  Deadline,
  OutcomeWord,
  STAGE_RULE,
  StageWord,
  WritingNote,
} from "./marks";

type Tab = "burning" | "all" | "mine" | Stage;

const TABS: { key: Tab; title: string }[] = [
  { key: "burning", title: "Горит" },
  { key: "drafting", title: "Пишутся" },
  { key: "moderation", title: "На проверке" },
  { key: "lawyers", title: "У юристов" },
  { key: "sent", title: "Отправлены" },
  { key: "mine", title: "Мои" },
  { key: "all", title: "Все" },
];

export function RemarksPage() {
  // Ссылка с карточки лота приходит с номером в адресе. Отбор живёт в
  // адресе, а не в памяти вкладки: так его можно переслать коллеге, и он
  // откроет ровно тот же список, а не соберёт фильтры заново с чужих слов.
  const [params, setParams] = useSearchParams();
  const lot = params.get("lot") ?? "";

  // Вкладка не выбрана, пока её не выбрали. Зашитое «Горит» открывало пустой
  // экран в тот день, когда ничего не горит: список выглядел сломанным ровно
  // тогда, когда всё в порядке. Со ссылки с карточки — сразу «Все»: там ищут
  // конкретный лот, и отбор по сроку его спрячет.
  const [picked, setPicked] = useState<Tab | null>(lot ? "all" : null);

  // Таблица по умолчанию, доска — по выбору: доской работают не все, а
  // список со сроками читают все. Вид всё так же живёт в адресе: ссылку на
  // доску отправляют коллеге, и открыться она должна доской.
  const board = params.get("vid") === "doska";
  const setBoard = (next: boolean) => {
    const now = new URLSearchParams(params);
    if (next) now.set("vid", "doska");
    else now.delete("vid");
    setParams(now, { replace: true });
  };
  const [extra, setExtra] = useState<Extra>({});
  const [search, setSearch] = useState(lot);

  // Кто смотрит — из той же записи, что открыла приложение. Без неё «Мои»
  // отбирал бы всё назначенное кому угодно.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });

  const { data: people } = useQuery({
    queryKey: ["people"],
    queryFn: cardsApi.people,
    staleTime: 10 * 60 * 1000,
  });

  // Отбор уходит на сервер: срок, сумма и код сужают выборку до десятков, и
  // тащить ради этого весь список в браузер незачем.
  const { data, isLoading, error } = useQuery({
    queryKey: ["remarks", extra],
    queryFn: () =>
      api.list({
        ends: extra.ends,
        outcome: extra.outcome,
        category: extra.category,
        enstru_code: extra.enstru_code,
        amount_from: extra.amount_from,
        amount_to: extra.amount_to,
        assignee_id: extra.assignee === "none" ? undefined : extra.assignee,
        unowned: extra.assignee === "none",
      }),
    // Список открыт по полдня, и на нём видно, как модель дописывает. Полминуты
    // — компромисс между «видно сразу» и запросами в пустой экран.
    refetchInterval: 30_000,
  });

  // Список без отбора — только ради чисел в списке сотрудников. Считать их
  // по отобранному нельзя: выбрав Иванова, мы получили бы «у всех остальных
  // ноль». Без отбора запрос тот же, и второго обращения не будет.
  const { data: everything } = useQuery({
    queryKey: ["remarks", "load"],
    queryFn: () => api.list({}),
    staleTime: 60_000,
  });
  const { data: jobs } = useQuery({
    queryKey: ["card-tasks", "open"],
    queryFn: () => cardsApi.tasks({ state: "open" }),
    staleTime: 60_000,
  });

  const all = useMemo(() => data ?? [], [data]);
  const counts = useMemo(() => countBy(all, me?.id), [all, me?.id]);
  const load = useMemo(
    () => loadOf(people ?? [], everything ?? [], jobs ?? []),
    [people, everything, jobs],
  );
  const tab = picked ?? opening(counts);
  // Категории берутся из данных, а не из справочника: у площадки он на
  // четыреста тысяч строк, а в работе категорий полтора десятка.
  const categories = useMemo(
    () => [...new Set(all.map((item) => item.category).filter(Boolean))].sort(),
    [all],
  );

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return all.filter((item) => {
      // На доске этап задают колонки, и вкладка по этапу спорила бы с ними.
      if (!belongs(item, board ? scoped(tab) : tab, me?.id)) return false;
      if (!needle) return true;
      return `${item.code} ${item.title} ${item.customer} ${item.row_id}`
        .toLowerCase()
        .includes(needle);
    });
  }, [all, tab, search, me?.id, board]);

  return (
    <>
      <PageHeader
        title="Обсуждения"
        subtitle="Замечания к техническим спецификациям до подачи заявки"
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
        <div className="flex flex-wrap items-center justify-between gap-3">
          {board ? (
            <Tabs
              tabs={SCOPES}
              value={scoped(tab)}
              counts={counts}
              onChange={setPicked}
              label="Чьи обсуждения"
            />
          ) : (
            <Tabs
              tabs={TABS}
              value={tab}
              counts={counts}
              onChange={setPicked}
            />
          )}

          <PeopleFilter
            people={load}
            value={extra.assignee ?? ""}
            onChange={(id) => setExtra({ ...extra, assignee: id || undefined })}
            total={(everything ?? []).length}
            unowned={
              (everything ?? []).filter((item) => !item.assignee_id).length
            }
            word={["обсуждение", "обсуждения", "обсуждений"]}
            label="Ответственный"
          />
          <Search
            value={search}
            onChange={(next) => {
              setSearch(next);
              // Ручная правка поиска убирает пришедший из адреса лот: иначе
              // ссылка остаётся в адресной строке и вводит в заблуждение при
              // пересылке.
              if (lot) setParams({}, { replace: true });
            }}
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

        {/* Ответственного выбирают выше, списком с числами: тот же отбор
            двумя разными способами на одном экране — это вопрос, который из
            них главнее, и ответа на него нет. */}
        <FilterBar value={extra} categories={categories} onChange={setExtra} />

        {isLoading ? (
          <Card className="px-5 py-4">
            <Spinner label="Читаем обсуждения…" />
          </Card>
        ) : error ? (
          <Card>
            <EmptyState
              title="Список не открылся"
              description={
                error instanceof Error
                  ? error.message
                  : "Попробуйте обновить страницу"
              }
            />
          </Card>
        ) : shown.length === 0 ? (
          <Card>
            <EmptyState
              title={tab === "burning" ? "Ничего не горит" : "Здесь пусто"}
              description={
                tab === "burning"
                  ? "Все сроки пока с запасом. Соседние вкладки покажут остальное."
                  : "Обсуждение заводится кнопкой на карточке лота."
              }
            />
          </Card>
        ) : board ? (
          <RemarkBoard items={shown} />
        ) : (
          <Card className="overflow-hidden">
            <Head />
            <ul>
              {shown.map((item) => (
                <Row key={item.id} remark={item} />
              ))}
            </ul>
          </Card>
        )}
      </Page>
    </>
  );
}

/** Шапка таблицы. Подписи мелкие: их читают один раз, а данные — постоянно. */
function Head() {
  return (
    <div
      className={cx(
        "grid grid-cols-[3px_5.5rem_minmax(0,1fr)_9rem_7rem_8rem_7.5rem] items-center gap-x-4",
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
      <span>Ведёт</span>
    </div>
  );
}

function Row({ remark }: { remark: Remark }) {
  return (
    <li className="border-b border-hairline last:border-0">
      <Link
        to={`/goszakup/remarks/${remark.id}`}
        className={cx(
          "grid grid-cols-[3px_5.5rem_minmax(0,1fr)_9rem_7rem_8rem_7.5rem] items-center gap-x-4",
          "py-2.5 pr-5 pl-0 transition hover:bg-plane",
        )}
      >
        {/* Полоса этапа. Держит взгляд на колонке при быстрой прокрутке —
            строку за строкой список из тридцати замечаний не читается. */}
        <span
          className={cx("h-8 w-[3px] rounded-r", STAGE_RULE[remark.stage])}
          aria-hidden
        />

        <span className="font-mono text-xs text-ink-muted">{remark.code}</span>

        <span className="min-w-0">
          <span className="block truncate text-sm text-ink">
            {remark.title}
          </span>
          <span className="mt-0.5 block truncate text-xs text-ink-muted">
            {remark.customer || remark.row_id}
          </span>
        </span>

        <span className="text-right text-sm tabular-nums text-ink-secondary">
          {remark.amount === null ? "—" : money(remark.amount)}
        </span>

        <Deadline remark={remark} />

        <span className="min-w-0">
          <StageWord remark={remark} />
          <span className="mt-0.5 block truncate">
            <OutcomeWord remark={remark} />
            <WritingNote remark={remark} />
          </span>
        </span>

        <span className="truncate text-sm">
          {remark.assignee ? (
            <span className="text-ink-secondary">{remark.assignee}</span>
          ) : (
            <span className="text-ink-muted">ничьё</span>
          )}
        </span>
      </Link>
    </li>
  );
}

/** Принадлежит ли замечание вкладке. */
/**
 * «Горит» — то, что ещё можно успеть.
 *
 * Прошедший срок сюда не идёт. Вкладку открывают, чтобы понять, за что взяться
 * сейчас, а лот с истёкшим приёмом ни к какому действию не ведёт: он копился
 * в ней неделями и оттеснял вниз то, у чего срок и правда завтра. Никуда он не
 * девается — «Все» и вкладка его этапа показывают его по-прежнему.
 */
function belongs(item: Remark, tab: Tab, me: string | undefined): boolean {
  if (tab === "all") return true;
  if (tab === "burning") return item.burning && !item.overdue;
  if (tab === "mine") return Boolean(me) && item.assignee_id === me;
  return item.stage === tab;
}

/**
 * Сколько в каждой вкладке.
 *
 * Считается один раз на весь набор, а не по разу на вкладку: семь проходов по
 * списку на каждое нажатие — это заметная задержка там, где человек просто
 * переключает вид.
 */
/**
 * На какой вкладке открыть список: горящее, потом своё, потом всё.
 *
 * Вкладку с нулём не открываем — пустой список на входе читается как поломка.
 */
function opening(counts: Record<Tab, number>): Tab {
  if (counts.burning) return "burning";
  if (counts.mine) return "mine";
  return "all";
}

/** Вкладки доски: этап показывают колонки, остаётся «чьи». */
const SCOPES: { key: Tab; title: string }[] = [
  { key: "burning", title: "Горит" },
  { key: "mine", title: "Мои" },
  { key: "all", title: "Все" },
];

/** Вкладка по этапу на доске оставила бы одну колонку из пяти. */
function scoped(tab: Tab): Tab {
  return SCOPES.some((item) => item.key === tab) ? tab : "all";
}

/** Сколько обсуждений и открытых задач на каждом сотруднике. */
function loadOf(
  people: { id: string; name: string }[],
  all: Remark[],
  jobs: { assignee_id: string }[],
): Load[] {
  return people.map((person) => ({
    id: person.id,
    name: person.name,
    rows: all.filter((item) => item.assignee_id === person.id).length,
    tasks: jobs.filter((task) => task.assignee_id === person.id).length,
  }));
}

function countBy(all: Remark[], me: string | undefined): Record<Tab, number> {
  const counts = {
    burning: 0,
    all: all.length,
    mine: 0,
    drafting: 0,
    moderation: 0,
    lawyers: 0,
    sent: 0,
    not_needed: 0,
  } as Record<Tab, number>;
  for (const item of all) {
    if (item.burning && !item.overdue) counts.burning += 1;
    if (me && item.assignee_id === me) counts.mine += 1;
    counts[item.stage] += 1;
  }
  return counts;
}
