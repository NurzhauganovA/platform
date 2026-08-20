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
DB_CONTAINER="${DB_CONTAINER:-fintend-postgres}"
DB="${DB:-fintend_tender}"

if [ -z "$NEW" ]; then
  echo "Укажите путь к архиву на этой машине: ./infra/repath.sh /srv/fintend/тендеры" >&2
  exit 1
fi

psql() { docker exec -i "$DB_CONTAINER" psql -U fintend -d "$DB" -tAc "$1"; }

if [ -z "$OLD" ]; then
  # Самый частый корень: в архиве десятки папок, и все они лежат под одним
  # каталогом — его и надо заменить.
  OLD="$(psql "
    select regexp_replace(root, '/[^/]+/[^/]+/?\$', '')
    from document_locations
    group by 1 order by count(*) desc limit 1")"
fi

if [ -z "$OLD" ]; then
  echo "Не нашёл, что заменять: в базе нет записей о местах документов." >&2
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

echo
echo "Проверка: путей под новым корнем — $(psql "select count(*) from document_locations where root like '$NEW%'")"
echo "Осталось под старым — $(psql "select count(*) from document_locations where root like '$OLD%'")"
echo
echo "Дальше проверьте, что файлы на месте: откройте любой разбор и ТЗ в нём."
