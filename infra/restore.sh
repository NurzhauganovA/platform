#!/usr/bin/env bash
#
# Разворачивает копию: четыре базы и загруженные файлы.
#
# Тем же скриптом делается и переезд на сервер — копия с рабочей машины
# разворачивается на новой. Отдельного «скрипта переезда» нет намеренно:
# переезд, который делается не тем же кодом, что восстановление, проверяется
# один раз в жизни и обычно в неподходящий момент.
#
#   ./infra/restore.sh backups/2026-08-19-1430
#
# Базы пересоздаются целиком. Это не «дописать поверх»: остатки прежних данных
# рядом с восстановленными — худший исход, потому что выглядит как рабочая
# платформа и врёт числами.

set -euo pipefail

cd "$(dirname "$0")/.."

FROM="${1:-}"
# Набор служб выбирается переменной `STACK`: рабочая — `fintend`, проверочная —
# `fintend-stage`. Так один и тот же скрипт обслуживает обе, и проверочная не
# заводит собственную копию, которая разойдётся с рабочей.
#
#   STACK=fintend-stage ./infra/restore.sh
DB_CONTAINER="${DB_CONTAINER:-${STACK:-fintend}-postgres}"

if [ -z "$FROM" ] || [ ! -d "$FROM" ]; then
  echo "Укажите каталог копии: ./infra/restore.sh backups/2026-08-19-1430" >&2
  exit 1
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  echo "База не запущена ($DB_CONTAINER)." >&2
  exit 1
fi

# Docker понимает только абсолютные пути, а каталог копии задают по-разному.
FROM="$(cd "$FROM" && pwd)"
echo "Разворачиваю $FROM"
echo "Существующие базы платформы будут удалены и созданы заново."
if [ "${YES:-}" != "1" ]; then
  read -r -p "Продолжаем? [y/N] " answer
  [ "$answer" = "y" ] || exit 1
fi

for dump in "$FROM"/*.dump; do
  [ -e "$dump" ] || continue
  db="$(basename "$dump" .dump)"
  echo "  $db"
  # Соединения рвутся до удаления: без этого `DROP DATABASE` упирается в
  # открытую сессию исполнителя и молча не выполняется.
  docker exec "$DB_CONTAINER" psql -U fintend -d postgres -tAc \
    "select pg_terminate_backend(pid) from pg_stat_activity where datname='$db'" >/dev/null
  docker exec "$DB_CONTAINER" psql -U fintend -d postgres -tAc \
    "drop database if exists $db" >/dev/null
  docker exec "$DB_CONTAINER" psql -U fintend -d postgres -tAc \
    "create database $db" >/dev/null
  docker exec -i "$DB_CONTAINER" pg_restore -U fintend -d "$db" --no-owner < "$dump"
done

if [ -f "$FROM/storage.tar.gz" ]; then
  echo "  загруженные файлы"
  docker run --rm -v platform_storage:/data -v "$FROM":/in alpine \
    sh -c 'rm -rf /data/* && tar xzf /in/storage.tar.gz -C /data'
fi

# Приставка тянется дальше сама. Без неё следующая команда пошла бы в рабочую
# базу — а её только что при человеке назвали «проверочной», и подмены он не
# заметит: обе отвечают одинаково.
PREFIX=""
[ "$DB_CONTAINER" = "fintend-postgres" ] || PREFIX="STACK=${STACK:-fintend} "

echo
echo "Готово. Дальше — пути к тендерному архиву:"
echo "  ${PREFIX}./infra/repath.sh /новый/путь/к/тендерам"
echo "  ${PREFIX}./infra/check-archive.sh"
echo
echo "В базе ядра лежат абсолютные пути документов. Если архив лежит не там,"
echo "где на машине, с которой снята копия, разбор не найдёт ни одного файла."
echo
echo "Копии с рабочего сервера этого шага не требуют: пути в них уже здешние."
