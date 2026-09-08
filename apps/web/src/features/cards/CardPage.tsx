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
import { Card as Panel, EmptyState, Spinner, Tabs } from "@/ui";
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
      {/* Экран в высоту окна, а не в поток страницы. Колонки прокручиваются
          порознь: слева таблица разбора на десять предметов, справа рельса
          шагов, и общая прокрутка уводила рельсу за верхний край ровно тогда,
          когда по таблице и надо свериться с задачей. */}
      <div className="flex h-screen flex-col overflow-hidden bg-plane">
        {/* Шапка своя, а не общая `PageHeader`: у лота в заголовке три разных
            вещи — код, название и откуда он.

            В одну строку и в одну строку названия. У лотов портала в названии
            лежит техническая спецификация целиком: развёрнутая, она занимает
            треть экрана, а читают её во вкладке «Разбор», где для неё место и
            есть. Здесь достаточно узнать лот. */}
        <header className="flex shrink-0 items-center gap-3 border-b border-hairline bg-surface px-[18px] py-[11px]">
          <span className="shrink-0 font-mono text-[12.5px] tracking-[0.02em] text-ink-muted">
            {data.code}
          </span>
          <h1
            className="min-w-0 truncate text-[15px] font-semibold tracking-[-0.015em] text-ink"
            title={data.title}
          >
            {data.title}
          </h1>
          <span className="ml-auto flex shrink-0 items-center gap-[7px]">
            <LotFacts card={data} />
            <PortalLink card={data} />
            <Link
              to="/work/lots"
              className="flex h-7 items-center rounded-[7px] border border-hairline bg-surface px-[11px] text-[12.5px] font-medium text-ink transition hover:bg-plane"
            >
              ← Ко всем лотам
            </Link>
          </span>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_352px] max-[1040px]:grid-cols-1">
          {/* Левая колонка со своей прокруткой; полоса подписей прилипает к её
              низу, а не к низу окна. */}
          <div className="flex min-w-0 flex-col overflow-auto">
            {/* Во всю ширину колонки, без своего потолка. Потолок в 1120
                точек оставлял справа полосу пустого фона до самой панели: на
                широком экране разбор упирался в невидимый край, а рядом
                пустовало место, которого таблице как раз не хватало. */}
            <div className="w-full flex-1 px-[18px] pt-[14px]">
              <Summary card={data} onDone={refresh} />

              {/* Вкладки строкой над содержимым, а не внутри его рамки:
                  так видно, что переключается весь блок, а не часть. */}
              <div className="mt-3 mb-2.5 flex items-center gap-0.5">
                <Tabs
                  tabs={TABS}
                  value={tab}
                  onChange={setTab}
                  label="Что смотрим"
                />
                {/* Подпись у вкладки, а не общая: «Разбор» и «Обсуждение»
                    легко перепутать — первое про площадку, второе про
                    заказчика. */}
                <span className="ml-auto truncate pl-4 text-xs text-ink-muted">
                  {ABOUT[tab]}
                </span>
              </div>

              {/* Рамку рисует сама вкладка, а не общая обёртка. У «Кто
                  работал» блоков три — числа, этапы и лента, — и общая рамка
                  вокруг них давала рамку в рамке: две линии в трёх точках от
                  друг друга читаются как сбой отрисовки. */}
              {tab === "source" && <SpecSheet card={data} />}
              {tab === "discussion" && <Discussion card={data} />}
              {tab === "files" && <Files card={data} />}
              {tab === "history" && <History card={data} />}

              <div className="h-4" />
            </div>

            <Approval card={data} onDone={refresh} />
          </div>

          {/* Правая колонка своим фоном и своей прокруткой — как отдельная
              поверхность: она про ход лота, а не про то, что открыто слева. */}
          <aside className="overflow-auto border-l border-hairline bg-plane/60 p-3 max-[1040px]:border-t max-[1040px]:border-l-0">
            <Rail card={data} people={people ?? []} onDone={refresh} />
          </aside>
        </div>
      </div>

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
