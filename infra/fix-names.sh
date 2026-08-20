#!/usr/bin/env bash
#
# Приводит имена в архиве к тому виду, в котором они записаны в базе ядра.
#
#   ./infra/fix-names.sh          покажет, что переименует
#   sudo ./infra/fix-names.sh -y  переименует
#
# Одну и ту же русскую букву Unicode позволяет записать двумя способами:
# «й» целиком или «и» плюс значок краткости. macOS ищет файл нечувствительно
# к этой разнице, ext4 сравнивает байты — и папка, разобранная на машине
# тендерщика, на сервере не находится при верном на вид пути.
#
# Правится диск, а не база. В базе тем же именем связаны решения по закупкам
# и находки поставщиков: они ключуются корнем и папкой, и переписать путь
# документа, не тронув остальные пять мест, значит получить базу, где файл
# открывается, а себестоимости по нему нет.
#
# Работает на самой машине, а не в контейнере: архив подключён туда только на
# чтение — и правильно, платформе незачем переименовывать чужие файлы.

set -euo pipefail

cd "$(dirname "$0")/.."

DB_CONTAINER="${DB_CONTAINER:-fintend-postgres}"
DB="${DB:-fintend_tender}"

APPLY=""
case "${1:-}" in
  -y | --yes) APPLY="1" ;;
  "") ;;
  *)
    echo "Знаю только -y (переименовать). Без него — примерка." >&2
    exit 1
    ;;
esac

if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  echo "База не запущена ($DB_CONTAINER)." >&2
  exit 1
fi

# Программа отдельной строкой, а не через `python3 -`: стандартный ввод занят
# списком путей, и питон прочитал бы как программу его.
PROGRAM="$(
  cat <<'PY'
import os
import sys
import unicodedata

apply = bool(os.environ.get("APPLY"))
renamed = missing = both = 0
shown = 0

# Имена, которые этот прогон уже создал. Один и тот же файл попадает в базу
# обеими формами, если его разбирали дважды: второй путь тогда просит
# переименовать обратно то, что выправил первый, и файл ходит туда-сюда,
# оставаясь недоступным по одному из двух путей. Ни один из них тут не
# «правильнее» — правится то, что чинится, остальное называется вслух.
made: set[str] = set()

# Пути идут по порядку, и это важно: папка чинится раньше файлов в ней, а одно
# её переименование выправляет сразу все пути под ней. В обратном порядке ту
# же папку пришлось бы искать столько раз, сколько в ней документов.
for line in sys.stdin:
    want = line.rstrip("\n")
    if not want or os.path.exists(want):
        continue

    # По колену за раз, сверху вниз: разойтись может любое из них, а какое
    # именно — видно только там, где путь перестаёт существовать.
    here = "/"
    for part in want.split("/")[1:]:
        step = os.path.join(here, part)
        if os.path.exists(step):
            here = step
            continue
        key = unicodedata.normalize("NFC", part)
        try:
            entries = os.listdir(here)
        except OSError:
            break
        found = next((e for e in entries if unicodedata.normalize("NFC", e) == key), None)
        if found is None:
            missing += 1
            break
        if os.path.join(here, found) in made:
            both += 1
            break
        if shown < 5:
            print(f"  {os.path.join(here, found)}\n→ {step}")
            shown += 1
        if apply:
            os.rename(os.path.join(here, found), step)
        made.add(step)
        renamed += 1
        here = step

print()
print(f"Расходящихся имён: {renamed}")
if missing:
    print(f"Не нашлось на диске ни в каком виде: {missing}")
if both:
    print(f"В базе записаны обе формы, взял первую: {both}")
if renamed and not apply:
    print()
    print("Это была примерка. Переименовать: sudo ./infra/fix-names.sh -y")
PY
)"

docker exec -i "$DB_CONTAINER" psql -U fintend -d "$DB" -tAc \
  "select distinct abs_path from document_locations order by 1" |
  APPLY="$APPLY" python3 -c "$PROGRAM"

echo
echo "Дальше — сверка: ./infra/check-archive.sh"
