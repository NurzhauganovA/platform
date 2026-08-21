#!/usr/bin/env bash
#
# Переписывает пути к тендерному архиву в базе ядра.
#
# В `fintend_tender` лежат абсолютные пути документов: разбор гонялся на
# машине тендерщика, и в базе осталось «/Users/…/Desktop/тендеры/…». На
# сервере архив лежит по другому пути, и без правки платформа не находит ни
# одного файла — список документов виден, а открыть нельзя.
#
#   ./infra/repath.sh /srv/fintend/тендеры
#   ./infra/repath.sh /srv/fintend/тендеры '/Users/user/Desktop/тендеры'
#
# Второй довод — старый путь. По умолчанию берётся самый частый корень из
# самой базы: угадывать тут нечего, он там записан.
#
# Правится сразу девять колонок в пяти таблицах. Забыть одну — значит получить
# базу, где документы находятся, а решения по закупкам нет: они ключуются
# корнем, и выборка молча вернёт пусто.

set -euo pipefail

NEW="${1:-}"
OLD="${2:-}"
# Набор служб выбирается переменной `STACK`: рабочая — `fintend`, проверочная —
# `fintend-stage`. Так один и тот же скрипт обслуживает обе, и проверочная не
# заводит собственную копию, которая разойдётся с рабочей.
#
#   STACK=fintend-stage ./infra/repath.sh
DB_CONTAINER="${DB_CONTAINER:-${STACK:-fintend}-postgres}"
DB="${DB:-fintend_tender}"

if [ -z "$NEW" ]; then
  echo "Укажите путь к архиву на этой машине: ./infra/repath.sh /srv/fintend/тендеры" >&2
  exit 1
fi

psql() { docker exec -i "$DB_CONTAINER" psql -U fintend -d "$DB" -tAc "$1"; }

if [ -z "$OLD" ]; then
  # Общее начало всех корней — его и надо заменить.
  #
  # Отрезать от корня несколько колен, как было сначала, нельзя: у одной
  # закупки путь «архив/фирма/дата/закупка», у другой «архив/фирма/дата/
  # техника/закупка», и любое постоянное число колен верно для части базы.
  # Переписывалась тогда тоже часть — остальные пути молча оставались вести
  # на прежнюю машину, а в разборе это выглядит как «файла нет на диске».
  #
  # Общее начало таково по построению: корни лежат в одном архиве.
  OLD="$(psql "select distinct root from document_locations" | awk '
    NR == 1 { common = $0; next }
    {
      limit = length(common); if (length($0) < limit) limit = length($0)
      same = 0
      while (same < limit && substr(common, same + 1, 1) == substr($0, same + 1, 1)) same++
      common = substr(common, 1, same)
    }
    # До ближайшей косой черты: общее начало обрывается посреди имени папки
    # («…/КАМАЗ» и «…/КАМены» дают «…/КАМ»), а у русских имён — и посреди
    # буквы, потому что awk считает байтами.
    END { sub(/\/[^\/]*$/, "", common); print common }')"
fi

if [ -z "$OLD" ]; then
  # Общего начала нет — значит, корни в базе от разных архивов. Так выглядит
  # база после наполовину прошедшего переезда: часть путей уже на сервере,
  # часть ещё ведёт на машину тендерщика. Угадывать тут нечего, и молча взять
  # один из двух — это переписать вторые поверх первых.
  echo "У корней в базе нет общего начала. Вот они:" >&2
  psql "
    select count(*) || '  ' || regexp_replace(root, '^(/[^/]+/[^/]+/[^/]+).*', '\\1')
    from document_locations group by 2 order by 1 desc limit 5" | sed 's/^/  /' >&2
  echo >&2
  echo "Позовите со старым корнем вторым доводом — для каждого свой вызов:" >&2
  echo "  ./infra/repath.sh $NEW '/Users/user/Desktop/тендеры'" >&2
  exit 1
fi

echo "Было:  $OLD"
echo "Стало: $NEW"
BEFORE="$(psql "select count(*) from document_locations where root like '$OLD%'")"
echo "Записей о местах под этим корнем: $BEFORE"
if [ "$BEFORE" = "0" ]; then
  echo "Под этим корнем ничего нет — проверьте старый путь." >&2
  exit 1
fi

if [ "${YES:-}" != "1" ]; then
  read -r -p "Переписываем? [y/N] " answer
  [ "$answer" = "y" ] || exit 1
fi

# Одной транзакцией: половина переписанных путей хуже, чем ни одного —
# документы найдутся, а решения по тем же закупкам нет.
docker exec -i "$DB_CONTAINER" psql -U fintend -d "$DB" -v ON_ERROR_STOP=1 <<SQL
begin;
update documents           set root = replace(root, '$OLD', '$NEW');
update documents           set abs_path = replace(abs_path, '$OLD', '$NEW');
update document_locations  set root = replace(root, '$OLD', '$NEW');
update document_locations  set abs_path = replace(abs_path, '$OLD', '$NEW');
update case_analyses       set root = replace(root, '$OLD', '$NEW');
update sourcing_results    set root = replace(root, '$OLD', '$NEW');
update price_observations  set root = replace(root, '$OLD', '$NEW');
commit;
SQL

MOVED="$(psql "select count(*) from document_locations where root like '$NEW%'")"
LEFT="$(psql "select count(*) from document_locations where root not like '$NEW%'")"
echo
echo "Путей под новым корнем: $MOVED"
if [ "$LEFT" != "0" ]; then
  echo
  echo "Осталось в стороне: $LEFT. Это пути, которые под новый корень не попали:"
  psql "
    select count(*) || '  ' || regexp_replace(root, '^(/[^/]+/[^/]+/[^/]+).*', '\\1')
    from document_locations where root not like '$NEW%'
    group by 2 order by 1 desc limit 5" | sed 's/^/  /'
  echo
  echo "Часть из них — разбор распакованных архивов: он читал файлы во"
  echo "временной папке, и её давно нет ни на одной машине. Остальное —"
  echo "второй архив; для него скрипт нужно позвать ещё раз со своим старым"
  echo "корнем вторым доводом."
fi
echo
echo "Дальше — сверка с диском глазами платформы:"
echo "  ./infra/check-archive.sh"
