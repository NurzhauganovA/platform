/**
 * Настройка обхода портала: номенклатура, по которой ищутся лоты.
 *
 * Экрана не было вовсе, хотя эндпоинты есть с самого модуля: список кодов
 * вели запросами к API. Пока код заводит тот, кто пишет эти запросы, это
 * работает; но список решает, что раздел вообще покажет, и вести его должен
 * тот, кто отвечает за номенклатуру, а не тот, у кого под рукой терминал.
 *
 * Правит только администратор — так же, как на сервере. Остальным список
 * виден: по нему понятно, что раздел молчит не потому, что закупок нет, а
 * потому что код выключен.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  goszakup,
  type Purge as PurgeCounts,
  type WatchedCode,
} from "@/api/goszakup";
import { auth } from "@/api/tender";
import { ApiError } from "@/api/client";
import { PageHeader } from "@/shell/AppShell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Page,
  Search,
  Spinner,
  Tabs,
  cx,
} from "@/ui";

type Tab = "active" | "off" | "all";

const TABS: { key: Tab; title: string }[] = [
  { key: "active", title: "В обходе" },
  { key: "off", title: "Выключены" },
  { key: "all", title: "Все" },
];

export function CodesPage() {
  const [tab, setTab] = useState<Tab>("active");
  const [search, setSearch] = useState("");
  const [code, setCode] = useState("");
  const [category, setCategory] = useState("");
  const [platform, setPlatform] = useState("");
  const [trouble, setTrouble] = useState("");

  const client = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: auth.me });
  const admin = me?.role === "admin";

  const { data, isLoading, error } = useQuery({
    queryKey: ["goszakup-codes"],
    queryFn: goszakup.codes,
  });

  const all = useMemo(() => data ?? [], [data]);
  const counts = useMemo(
    () => ({
      active: all.filter((item) => item.active).length,
      off: all.filter((item) => !item.active).length,
      all: all.length,
    }),
    [all],
  );

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return all.filter((item) => {
      if (tab === "active" && !item.active) return false;
      if (tab === "off" && item.active) return false;
      if (!needle) return true;
      return `${item.code} ${item.name} ${item.category} ${item.note}`
        .toLowerCase()
        .includes(needle);
    });
  }, [all, tab, search]);

  // Сообщение об отказе показывается словами сервера: «код уже в списке» и
  // «такого кода в справочнике нет» — разные беды, и общее «не получилось»
  // заставляет гадать, какая из них.
  const refresh = () => {
    setTrouble("");
    void client.invalidateQueries({ queryKey: ["goszakup-codes"] });
  };
  const complain = (err: unknown) =>
    setTrouble(err instanceof ApiError ? err.message : "Не получилось");

  const adding = useMutation({
    mutationFn: () => goszakup.add(code.trim(), category.trim(), "", platform),
    onSuccess: () => {
      setCode("");
      setCategory("");
      setPlatform("");
      refresh();
    },
    onError: complain,
  });

  const reviving = useMutation({
    mutationFn: (item: WatchedCode) => goszakup.revive(item.code),
    onSuccess: refresh,
  });

  const dropping = useMutation({
    mutationFn: (item: WatchedCode) => goszakup.drop(item.code),
    onSuccess: refresh,
    onError: complain,
  });

  const moving = useMutation({
    mutationFn: (next: { code: string; platform: string }) =>
      goszakup.setPlatform(next.code, next.platform),
    onSuccess: refresh,
    onError: complain,
  });

  const naming = useMutation({
    mutationFn: (next: { code: string; category: string }) =>
      goszakup.setCategory(next.code, next.category),
    onSuccess: refresh,
    onError: complain,
  });

  return (
    <>
      <PageHeader
        title="Обход портала"
        subtitle="Коды ЕНС ТРУ, по которым собираются лоты zakup.gov.kz"
        action={
          <span className="text-sm text-ink-secondary">
            в обходе <b className="font-semibold text-ink">{counts.active}</b>{" "}
            из {counts.all}
          </span>
        }
      />

      <Page>
        {admin && <Purge onDone={refresh} />}

        {counts.active === 0 && !isLoading && (
          <Card className="border-warning/40 bg-warning/5 px-5 py-3">
            <p className="text-sm text-ink">
              В обходе нет ни одного кода — раздел «Лоты портала» останется
              пустым. Обход идёт строго по этому списку.
            </p>
          </Card>
        )}

        {admin && (
          <Card title="Добавить код">
            <form
              className="flex flex-wrap items-end gap-3 px-5 py-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (code.trim()) adding.mutate();
              }}
            >
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-ink">
                  Код ЕНС ТРУ
                </span>
                <Input
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  placeholder="262013.000.000011"
                  className="w-52 font-mono"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-ink">
                  Наша категория
                </span>
                <Input
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  placeholder="Компьютеры"
                  className="w-52"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-ink">
                  Площадка
                </span>
                <Places value={platform} onChange={setPlatform} />
              </label>
              <Button
                type="submit"
                variant="primary"
                disabled={!code.trim() || adding.isPending}
              >
                {adding.isPending ? "Добавляем…" : "Добавить"}
              </Button>
              <p className="w-full text-xs text-ink-muted">
                Название подтянется из справочника портала. Лишний код — это
                сотни чужих лотов в списке и запросы к порталу за ними.
              </p>
            </form>
          </Card>
        )}

        {trouble && (
          <Card className="border-critical/40 bg-critical/5 px-5 py-3">
            <p className="text-sm text-critical">{trouble}</p>
          </Card>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs tabs={TABS} value={tab} counts={counts} onChange={setTab} />
          <Search
            value={search}
            onChange={setSearch}
            placeholder="Код, название, категория"
          />
        </div>

        {isLoading && (
          <Card className="px-5 py-8">
            <Spinner label="Читаем список…" />
          </Card>
        )}

        {error && (
          <Card className="px-5 py-8">
            <EmptyState
              title="Список не открылся"
              description={
                error instanceof ApiError && error.isForbidden
                  ? "Вашей роли раздел госзакупок не открыт."
                  : "Сервер не ответил. Попробуйте обновить страницу."
              }
            />
          </Card>
        )}

        {data && shown.length === 0 && (
          <Card className="px-5 py-8">
            <EmptyState
              title={search ? "Ничего не нашлось" : "Здесь пусто"}
              description={
                search
                  ? "Попробуйте искать по части кода или по категории."
                  : "Соседние вкладки покажут остальное."
              }
            />
          </Card>
        )}

        {data && shown.length > 0 && (
          <Card>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-xs text-ink-muted">
                  <th className="px-5 py-2 font-medium">Код</th>
                  <th className="px-5 py-2 font-medium">Название на портале</th>
                  <th className="px-5 py-2 font-medium">Площадка</th>
                  <th className="px-5 py-2 font-medium">Наша категория</th>
                  <th className="px-5 py-2 font-medium">Состояние</th>
                  {admin && <th className="px-5 py-2" />}
                </tr>
              </thead>
              <tbody>
                {shown.map((item) => (
                  <tr
                    key={item.code}
                    className={cx(
                      "border-b border-hairline last:border-0",
                      !item.active && "text-ink-muted",
                    )}
                  >
                    <td className="px-5 py-2.5 font-mono text-xs whitespace-nowrap">
                      {item.code}
                    </td>
                    <td className="px-5 py-2.5">
                      {item.name || (
                        <span className="text-ink-muted">
                          в справочнике не нашлось
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-2.5">
                      {admin ? (
                        <Places
                          value={item.platform}
                          onChange={(next) =>
                            moving.mutate({ code: item.code, platform: next })
                          }
                        />
                      ) : (
                        item.platform || (
                          <span className="text-ink-muted">все</span>
                        )
                      )}
                    </td>
                    <td className="px-5 py-2.5">
                      {admin ? (
                        <CategoryCell
                          value={item.category}
                          onSave={(next) =>
                            naming.mutate({ code: item.code, category: next })
                          }
                        />
                      ) : (
                        item.category || (
                          <span className="text-ink-muted">не задана</span>
                        )
                      )}
                    </td>
                    <td className="px-5 py-2.5">
                      {item.active ? (
                        <Badge tone="good">В обходе</Badge>
                      ) : (
                        <Badge tone="neutral">Выключен</Badge>
                      )}
                    </td>
                    {admin && (
                      <td className="px-5 py-2.5 text-right">
                        {item.active ? (
                          <Button
                            variant="ghost"
                            onClick={() => dropping.mutate(item)}
                            disabled={dropping.isPending}
                            title="Обход перестанет брать этот код. Строка останется — включить обратно проще, чем набирать двенадцать цифр заново."
                          >
                            Выключить
                          </Button>
                        ) : (
                          /* Обратная кнопка. Без неё выключенный код было
                             нечем вернуть: строка оставалась в списке, а в
                             обход её возвращали заведением заново — теряя
                             категорию и площадку. */
                          <Button
                            variant="ghost"
                            onClick={() => reviving.mutate(item)}
                            disabled={reviving.isPending}
                            title="Обход снова начнёт брать этот код — со следующего обновления."
                          >
                            Включить
                          </Button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Page>
    </>
  );
}

/**
 * Выбор площадки единого портала.
 *
 * Портал один, площадок в нём несколько, и лоты лежат вперемешку. Пусто —
 * искать на всех: сузить отбор проще, чем однажды обнаружить, что половина
 * закупок не приходит.
 */
function Places({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cx(
        "w-40 rounded-[8px] border border-baseline bg-surface px-2.5 py-1.5",
        "text-sm text-ink focus:border-series-1 focus:outline-none",
      )}
    >
      <option value="">все площадки</option>
      <option value="ЭГЗ">ЭГЗ — госзакупки</option>
      <option value="Mitwork">Mitwork</option>
      <option value="SKK">SKK — Самрук</option>
    </select>
  );
}

/**
 * Категория правится на месте.
 *
 * Коды заводят пачкой, а категории пересматривают позже — когда становится
 * ясно, кто что ведёт. Отдельный экран правки ради одного поля означал бы
 * три нажатия там, где хватает одного.
 */
function CategoryCell({
  value,
  onSave,
}: {
  value: string;
  onSave: (next: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const changed = draft.trim() !== value;

  return (
    <span className="flex items-center gap-2">
      <Input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="не задана"
        className="w-44 py-1"
      />
      {changed && (
        <Button variant="ghost" onClick={() => onSave(draft.trim())}>
          Сохранить
        </Button>
      )}
    </span>
  );
}

/**
 * Очистка раздела: удалить все лоты портала и всё, что к ним приросло.
 *
 * Нужна, когда список разошёлся с порталом настолько, что чинить дешевле
 * заново. Спрятана под раскрытие и показывает числа до нажатия: соглашаться
 * человек должен на «17 карточек и 6 реплик», а не на слово «всё» — за ними
 * стоит чужая работа.
 *
 * Второе нажатие подтверждает. Диалога браузера здесь нет намеренно: он
 * выглядит одинаково для «сохранить черновик» и «стереть работу отдела», и
 * его закрывают не читая.
 */
function Purge({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [sure, setSure] = useState(false);
  const [trouble, setTrouble] = useState("");
  const [done, setDone] = useState<PurgeCounts | null>(null);

  const ahead = useQuery({
    queryKey: ["goszakup-purge"],
    queryFn: goszakup.purgePreview,
    enabled: open,
    staleTime: 0,
  });

  const wipe = useMutation({
    mutationFn: goszakup.purge,
    onSuccess: (result) => {
      setDone(result);
      setSure(false);
      setOpen(false);
      onDone();
    },
    onError: (error) =>
      setTrouble(error instanceof ApiError ? error.message : "Не получилось"),
  });

  if (done) {
    return (
      <Card className="border-good/40 bg-good/5 px-5 py-3">
        <p className="text-sm text-ink">
          ✓ Удалено: лотов {done.lots}, карточек {done.cards}, обсуждений{" "}
          {done.remarks}, реплик {done.messages}, кодов строк {done.codes}.
          Список кодов ЕНС ТРУ остался — нажмите «Обновить данные» в разделе
          «Лоты портала».
        </p>
      </Card>
    );
  }

  return (
    <Card className="px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-sm font-semibold text-ink">Очистка раздела</h2>
        <p className="flex-1 text-sm text-ink-muted">
          Удаляет все лоты портала вместе с карточками, задачами и обсуждениями.
          Список кодов остаётся.
        </p>
        <Button variant="ghost" onClick={() => setOpen((was) => !was)}>
          {open ? "Не надо" : "Удалить все лоты"}
        </Button>
      </div>

      {open && (
        <div className="mt-3 border-t border-hairline pt-3">
          {ahead.isLoading && <Spinner label="Считаем, что удалится…" />}
          {ahead.data && (
            <>
              <p className="text-sm text-ink">
                Уйдёт безвозвратно: <b>{ahead.data.lots}</b> лотов,{" "}
                <b>{ahead.data.cards}</b> карточек в работе,{" "}
                <b>{ahead.data.remarks}</b> обсуждений с заказчиком,{" "}
                <b>{ahead.data.messages}</b> реплик переписки,{" "}
                <b>{ahead.data.codes}</b> устойчивых кодов. Задачи, подписи и
                лента событий уйдут вместе с карточками.
              </p>
              <p className="mt-1 text-sm text-ink-muted">
                Отменить нельзя. Коды строк выдадутся заново, и «GZ000045» в
                старой задаче будет означать другой лот.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {!sure ? (
                  <Button variant="danger" onClick={() => setSure(true)}>
                    Понимаю, удалить
                  </Button>
                ) : (
                  <Button
                    variant="danger"
                    onClick={() => wipe.mutate()}
                    disabled={wipe.isPending}
                  >
                    {wipe.isPending
                      ? "Удаляем…"
                      : `Удалить ${ahead.data.total} записей`}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  onClick={() => {
                    setOpen(false);
                    setSure(false);
                  }}
                >
                  Отмена
                </Button>
              </div>
            </>
          )}
          {trouble && <p className="mt-2 text-sm text-critical">{trouble}</p>}
        </div>
      )}
    </Card>
  );
}
