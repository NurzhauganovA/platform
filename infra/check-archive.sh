#!/usr/bin/env bash
#
# Сверяет пути документов в базе ядра с тем, что видит платформа на диске.
#
#   ./infra/check-archive.sh
#
# «Нет на диске» в разборе — это всегда один из пяти случаев, и снаружи они
# выглядят одинаково: архив не подключён томом, пути в базе ведут на прежнюю
# машину, у платформы нет прав на чтение, имя длиннее того, что принимает
# файловая система, или имя записано в другой форме Unicode. Два последних
# коварнее прочих: на macOS поиск файла нечувствителен к форме записи, на ext4
# он побайтовый, а предел длины там считается в байтах, а не в буквах.
#
# Смотрит изнутри контейнера: важно не то, что видно в терминале сервера, а то,
# до чего дотягивается сам API. Прав у них разные — сервером распоряжается
# человек, платформа работает под своим uid.

set -euo pipefail

cd "$(dirname "$0")/.."

# Набор служб выбирается переменной `STACK`: рабочая — `fintend`, проверочная —
# `fintend-stage`. Так один и тот же скрипт обслуживает обе, и проверочная не
# заводит собственную копию, которая разойдётся с рабочей.
#
#   STACK=fintend-stage ./infra/check-archive.sh
CONTAINER="${CONTAINER:-${STACK:-fintend}-api}"

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


def on_disk(path: Path) -> Path:
    """Путь так, как имя записано на диске: колено за коленом.

    Целиком приводить путь нельзя — написание расходится по коленам вразнобой,
    и приведённый целиком путь не совпадёт ни с чем. Тем же способом ищет файл
    и сама платформа.
    """
    if look(path) != "нет":
        return path
    here = Path(path.anchor)
    for part in path.parts[1:]:
        step = here / part
        if look(step) == "нет":
            key = unicodedata.normalize("NFC", part)
            try:
                entries = list(here.iterdir())
            except OSError:
                return path
            found = next((e for e in entries if unicodedata.normalize("NFC", e.name) == key), None)
            if found is None:
                return path
            step = found
        here = step
    return here


def look(path: Path) -> str:
    """Что видно по этому пути: «файл», «папка», «нет», «нет прав», «не имя»."""
    try:
        if path.is_file():
            return "файл"
        return "папка" if path.is_dir() else "нет"
    except PermissionError:
        return "нет прав"
    except OSError:
        # Имя длиннее того, что принимает файловая система: не «файла нет»,
        # а «такой файл здесь невозможен».
        return "не имя"


# Проход один. Для каждого пути важно не «есть или нет», а почему нет: по
# одному числу «не найдено 3948» чинить нечего.
verdicts: Counter[str] = Counter()
examples: dict[str, list[str]] = {}
roots: Counter[str] = Counter()

for text in paths:
    path = Path(text)
    roots["/".join(text.split("/")[:4])] += 1
    seen = look(path)
    if seen == "файл":
        verdicts["на месте"] += 1
        continue
    if seen == "нет прав":
        why = "лежит, но платформе не даны права на чтение"
    elif seen == "не имя" or any(len(part.encode()) > 255 for part in path.parts):
        why = "имя длиннее 255 байт — файловая система Linux его не примет"
    else:
        if look(on_disk(path)) == "файл":
            why = "есть на диске, имя записано в другой форме — платформа найдёт"
        elif look(on_disk(path.parent)) != "папка":
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
notes = {
    "папка": "виден",
    "файл": "виден",
    "нет": "НЕ ВИДЕН из контейнера",
    "нет прав": "НЕТ ПРАВ у платформы",
    "не имя": "имя не по силам файловой системе",
}
for root, count in roots.most_common(5):
    print(f"  {count:>5}  {root}  — {notes[look(Path(root))]}")

if any("права" in why or "прав" in why for why in verdicts):
    print()
    print("Права. Платформа работает под uid 10001, а архив приехал с правами")
    print("прежней машины — «только владельцу». Открыть его на чтение:")
    print()
    print("  sudo chmod -R a+rX /srv/fintend/tenders")
    print()
    print("Писать туда она всё равно не сможет: том подключён только на чтение.")
PY
