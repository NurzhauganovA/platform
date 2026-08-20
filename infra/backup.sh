#!/usr/bin/env bash
#
# Копия всего, что нельзя пересобрать: четыре базы и загруженные файлы.
#
# Образы, каталог `.docker` и код в копию не идут — они собираются заново из
# репозиториев. Копируется только то, чего больше нигде нет.
#
# Архив тендерных папок сюда тоже не входит, и это осознанно: он подключён
# томом с диска сервера и живёт своей жизнью, а класть два гигабайта в
# ежедневную копию значит забить диск за месяц. Его копируют отдельно и реже —
# он почти не меняется.
#
#   ./infra/backup.sh              в ./backups
#   BACKUP_DIR=/mnt/nas ./infra/backup.sh
#
# Копия рядом с сервером — это не копия. Пожар, кража и шифровальщик забирают
# и машину, и диск в ней: увозите её из здания.

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d-%H%M)"
OUT="$BACKUP_DIR/$STAMP"
DB_CONTAINER="${DB_CONTAINER:-fintend-postgres}"

if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  echo "База не запущена ($DB_CONTAINER). Копировать нечего." >&2
  exit 1
fi

mkdir -p "$OUT"
# Абсолютный путь: каталог копии задают и относительным, и абсолютным, а
# Docker понимает только второй. Без этого `-v "$PWD/$OUT"` на абсолютном
# пути склеивал два корня и клал архив в никуда.
OUT="$(cd "$OUT" && pwd)"
echo "Копия в $OUT"

# Базы по одной, а не одним `pg_dumpall`: развернуть обратно нужно бывает
# только тендерную или только платформу, и вытаскивать её из общего дампа
# руками — это работа в тот час, когда всё и так лежит.
for db in fintend fintend_tender fintend_skstore fintend_omarket; do
  if docker exec "$DB_CONTAINER" psql -U fintend -tAc \
      "select 1 from pg_database where datname='$db'" | grep -q 1; then
    docker exec "$DB_CONTAINER" pg_dump -U fintend --format=custom "$db" \
      > "$OUT/$db.dump"
    echo "  $db — $(du -h "$OUT/$db.dump" | cut -f1)"
  else
    echo "  $db — нет такой базы, пропущено"
  fi
done

# Загруженные тендерные папки лежат в томе: из него их и берём. Том переживает
# пересборку образа, но не `docker compose down -v` и не отказ диска.
if docker volume inspect platform_storage >/dev/null 2>&1; then
  docker run --rm -v platform_storage:/data -v "$OUT":/out alpine \
    tar czf /out/storage.tar.gz -C /data .
  echo "  файлы — $(du -h "$OUT/storage.tar.gz" | cut -f1)"
fi

# Проверка, а не надежда: битый дамп выглядит как обычный файл, и узнаётся об
# этом в тот единственный день, когда он нужен.
for dump in "$OUT"/*.dump; do
  [ -e "$dump" ] || continue
  if ! docker exec -i "$DB_CONTAINER" pg_restore --list >/dev/null 2>&1 < "$dump"; then
    echo "  ! $(basename "$dump") не читается — копия негодна" >&2
    exit 1
  fi
done
echo "Дампы читаются."

# Старые копии убираются сами: без этого диск кончается через несколько
# месяцев, и заметно это становится по тому, что перестала писаться свежая.
find "$BACKUP_DIR" -maxdepth 1 -type d -name '20*' -mtime "+$KEEP_DAYS" -print0 |
  while IFS= read -r -d '' old; do
    echo "Удаляю старую копию: $(basename "$old")"
    rm -rf "$old"
  done

echo
echo "Готово. Копия рядом с сервером не спасёт от пожара — увезите её."
