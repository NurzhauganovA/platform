#!/usr/bin/env bash
#
# Сверяет пути документов в базе ядра с тем, что видит платформа на диске.
#
#   ./infra/check-archive.sh
#
# «Нет на диске» в разборе — это всегда один из четырёх случаев, и снаружи они
# выглядят одинаково: архив не подключён томом, пути в базе ведут на прежнюю
# машину, имя длиннее того, что принимает файловая система, или имя записано
# в другой форме Unicode. Последнее коварнее прочих: на macOS поиск файла
# нечувствителен к форме записи, на ext4 — побайтовый, и папка, разобранная на
# машине тендерщика, на сервере не находится при верном на вид пути.
#
# Смотрит изнутри контейнера: важно не то, что видно в терминале сервера, а то,
# до чего дотягивается сам API.

set -euo pipefail

cd "$(dirname "$0")/.."

CONTAINER="${CONTAINER:-fintend-api}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Контейнер $CONTAINER не запущен. Сначала: make prod" >&2
  exit 1
fi

docker exec -i "$CONTAINER" python - <<'PY'
import os
import unicodedata
from collections import Counter
from pathlib import Path

import psycopg

url = os.environ["TENDER__DB__URL"].replace("+psycopg", "")

# Одним запросом и без повторов: один и тот же файл лежит в нескольких
# закупках, а проверять его на диске нужно один раз.
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute("select distinct abs_path from document_locations")
    paths = [row[0] for row in cur]

# Проход один. Для каждого пути важно не «есть или нет», а почему нет:
# по одному числу «не найдено 3948» чинить нечего.
verdicts: Counter[str] = Counter()
examples: dict[str, list[str]] = {}
roots: Counter[str] = Counter()

for text in paths:
    path = Path(text)
    roots["/".join(text.split("/")[:4])] += 1
    if path.is_file():
        verdicts["на месте"] += 1
        continue
    other = "NFC" if unicodedata.normalize("NFD", text) == text else "NFD"
    if Path(unicodedata.normalize(other, text)).is_file():
        why = f"есть на диске, но в другой форме записи ({other})"
    elif any(len(part.encode()) > 255 for part in path.parts):
        why = "имя длиннее 255 байт — файловая система Linux его не примет"
    elif not path.parent.is_dir():
        why = "нет самой папки закупки"
    else:
        why = "папка есть, файла в ней нет"
    verdicts[why] += 1
    examples.setdefault(why, []).append(text)

print(f"Путей в базе (без повторов): {len(paths)}")
print()
for why, count in verdicts.most_common():
    print(f"  {count:>5}  {why}")
    for sample in examples.get(why, [])[:2]:
        print(f"         {sample}")
print()
print("Корни, под которыми записаны пути:")
for root, count in roots.most_common(5):
    seen = "виден" if Path(root).is_dir() else "НЕ ВИДЕН из контейнера"
    print(f"  {count:>5}  {root}  — {seen}")
PY
