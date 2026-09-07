/**
 * Карточка лота: всё, что с ним происходит, на одном экране.
 *
 * Хаб, а не ещё одна страница. Отвечает на вопрос, ради которого её
 * открывают: где лот и чьего хода ждут.
 *
 * **Вкладками, а не лентой блоков.** Блоков стало девять — сведения, разбор,
 * обсуждение, согласование, задачи, файлы, переписка, история, действия, — и
 * в столбик это четыре экрана прокрутки. Человек, зашедший подписать, крутил
 * мимо разбора; зашедший прочитать спецификацию — мимо задач. Наверху
 * остаётся то, что нужно всем: где лот, сколько осталось и чья подпись; всё
 * остальное разложено по вкладкам, и каждая прокручивается сама.
 *
 * Действия справа отдельным столбцом. Внизу их не найти, а вверху они зовут
 * нажать раньше, чем прочитано согласование.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { cardsApi, type Card } from "@/api/cards";
import { Card as Panel, EmptyState, Page, Spinner, Tabs } from "@/ui";
import { Discussion } from "./Discussion";
import { ChatDock } from "./ChatDock";
import { Files } from "./Files";
import { LotFacts, PortalLink } from "./LotFacts";
import { Approval, Summary } from "./Head";
import { History } from "./History";
import { Rail } from "./Rail";
import { SpecSheet } from "./SpecSheet";

export function CardPage() {
  const { id = "" } = useParams();
  const cache = useQueryClient();
  // Первым — обсуждение: оно пишется под срок. Данные закупки вкладкой
  // быть перестали: их открывают панелью справа с любой вкладки.
  const [tab, setTab] = useState<Tab>("discussion");

  const { data, isLoading, error } = useQuery({
    queryKey: ["card", id],
    queryFn: () => cardsApi.one(id),
  });
  const { data: people } = useQuery({
    queryKey: ["people"],
    queryFn: cardsApi.people,
    staleTime: 10 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="px-8 py-6">
        <Panel className="px-5 py-6">
          <Spinner label="Открываем лот…" />
        </Panel>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="px-8 py-6">
        <Panel className="px-5 py-8">
          <EmptyState
            title="Лот не открылся"
            description={
              error instanceof Error ? error.message : "Возможно, его убрали"
            }
            action={
              <Link
                to="/work/lots"
                className="rounded-[8px] border border-baseline px-3 py-1.5 text-sm text-ink transition hover:bg-plane"
              >
                Ко всем лотам
              </Link>
            }
          />
        </Panel>
      </div>
    );
  }

  const refresh = (fresh: Card) => cache.setQueryData(["card", id], fresh);

  return (
    <>
      {/* Шапка своя, а не общая `PageHeader`: у лота в заголовке три разных
          вещи — код, название и откуда он.

          В одну строку и в одну строку названия. У лотов портала в названии
          лежит техническая спецификация целиком: развёрнутая, она занимает
          треть экрана, а читают её во вкладке «Разбор», где для неё место и
          есть. Здесь достаточно узнать лот. */}
      <header className="flex items-center gap-4 border-b border-hairline bg-surface px-8 py-2.5">
        <h1 className="flex min-w-0 items-baseline gap-2 text-[15px] font-semibold tracking-tight text-ink">
          <span className="shrink-0 font-mono">{data.code}</span>
          <span aria-hidden className="shrink-0 text-ink-muted">
            ·
          </span>
          <span className="truncate" title={data.title}>
            {data.title}
          </span>
        </h1>

        {/* Заказчик, площадка и номера отсюда убраны. Всё это есть в
            «Данных закупки» — а в шапке они занимали половину строки, и
            название лота, ради которого шапку и читают, ужималось до
            многоточия. */}
        <span className="ml-auto flex shrink-0 items-center gap-2">
          <LotFacts card={data} />
          <PortalLink card={data} />
        </span>

        <Link
          to="/work/lots"
          className="shrink-0 rounded-[8px] border border-baseline px-2.5 py-1 text-xs text-ink transition hover:bg-plane"
        >
          ← Ко всем лотам
        </Link>
      </header>

      {/* Шире обычной страницы: в карточке рядом стоят таблица разбора и
          правый столбец, и на восьми отступах по краям таблица начинала
          прокручиваться вбок уже на четырёх столбцах. */}
      <Page className="space-y-3 px-4">
        {/* Ширина правого столбца задаётся его содержимым, а не числом:
            свёрнутый он ужимается до полоски, и освободившееся место уходит
            вкладкам само. Второе число в сетке пришлось бы держать в двух
            местах — здесь и в самой колонке. */}
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4">
          <div className="min-w-0 space-y-3">
            <Summary card={data} onDone={refresh} />

            <Panel className="overflow-hidden">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-hairline px-5">
                <Tabs
                  tabs={TABS}
                  value={tab}
                  onChange={setTab}
                  label="Что смотрим"
                />
                {/* Подпись у вкладки, а не общая: «Разбор» и «Обсуждение»
                    легко перепутать — первое про площадку, второе про
                    заказчика. */}
                <p className="ml-auto py-2 text-xs text-ink-muted">
                  {ABOUT[tab]}
                </p>
              </div>

              <div className="px-5 py-4">
                {tab === "source" && <SpecSheet card={data} />}
                {tab === "discussion" && <Discussion card={data} />}
                {tab === "files" && <Files card={data} />}
                {tab === "history" && <History card={data} />}
              </div>
            </Panel>

            {/* Согласование внизу, а не над вкладками. Подписывают его
                ежедневно, но карточку открывают ради другого: разобрать
                закупку и написать заказчику. Полоса подписей над содержимым
                отодвигала работу на пол-экрана вниз ради шага, который делают
                в конце. Кому надо подписать — тот видит кнопку в «Что дальше»
                справа, она никуда не уехала. */}
            <Approval card={data} onDone={refresh} />
          </div>

          <Rail card={data} people={people ?? []} onDone={refresh} />
        </div>
      </Page>

      {/* Поверх страницы, а не в сетке: переписку ведут, не уходя с той
          вкладки, о которой пишут. */}
      <ChatDock card={data} />
    </>
  );
}

type Tab = "discussion" | "source" | "files" | "history";

const TABS: { key: Tab; title: string }[] = [
  { key: "discussion", title: "Обсуждение" },
  { key: "source", title: "Разбор" },
  { key: "files", title: "Файлы" },
  { key: "history", title: "Кто работал" },
];

/** Чем эта вкладка отличается от соседней. Одного названия мало. */
const ABOUT: Record<Tab, string> = {
  discussion: "официальное обращение к заказчику до подачи заявки",
  source: "спецификация заказчика, разложенная по предметам",
  files: "спецификация заказчика и то, что приложили мы",
  history: "кто что делал — по этому считаем премию",
};
