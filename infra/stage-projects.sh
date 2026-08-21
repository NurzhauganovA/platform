#!/usr/bin/env bash
#
# Готовит исходники подключённых проектов к сборке образа.
#
# Зачем это вообще нужно. Платформа импортирует три соседних пакета напрямую,
# а лежат они вне её каталога — и в разных деревьях: `tender-analyze` и
# `skstore` рядом, `omarket` в `~/Desktop/github`. Docker умеет читать только
# то, что лежит внутри контекста сборки, а общий предок этих трёх — рабочий
# стол целиком. Отдавать его демону значит читать перед каждой сборкой всё,
# что там накопилось.
#
# Свежий Compose умеет несколько контекстов сразу (`additional_contexts`), и
# тогда скрипт был бы не нужен. Здесь стоит 2.7, где этого ещё нет, поэтому
# исходники переносятся сюда явно.
#
# Копируется только исходный код. Базы не копируются намеренно: у skstore она
# весит четыреста мегабайт, и её место в томе, а не в слое образа — иначе
# каждая пересборка тащила бы её заново, а данные внутри образа устаревали бы
# в тот же день.
#
# Пути можно переопределить переменными окружения — раскладка каталогов у
# каждого своя:
#
#   TENDER_DIR=~/code/tender-analyze ./infra/stage-projects.sh

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Пути берутся оттуда же, откуда их берёт Compose: сначала окружение, потом
# `.env`, потом умолчание. Разные источники у скрипта и у Compose означали бы
# сборку из одного каталога и запуск с томами из другого — и выяснилось бы
# это не сразу, а на первой странице с пустым списком.
from_env() {
  [ -f "$here/.env" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$here/.env" | tail -1 | tr -d '"'"'"'\r'
}

TENDER_DIR="${TENDER_DIR:-$(from_env TENDER_DIR)}"
SKSTORE_DIR="${SKSTORE_DIR:-$(from_env SKSTORE_DIR)}"
OMARKET_DIR="${OMARKET_DIR:-$(from_env OMARKET_DIR)}"

TENDER_DIR="${TENDER_DIR:-../tender-analyze}"
SKSTORE_DIR="${SKSTORE_DIR:-../skstore}"
OMARKET_DIR="${OMARKET_DIR:-../../github/omarket}"

# Относительный путь считается от каталога платформы, а не от того, откуда
# запустили: Compose считает его так же, и разойтись они не должны.
absolute() { case "$1" in /*) printf %s "$1" ;; *) printf %s "$here/$1" ;; esac; }
TENDER_DIR="$(absolute "$TENDER_DIR")"
SKSTORE_DIR="$(absolute "$SKSTORE_DIR")"
OMARKET_DIR="$(absolute "$OMARKET_DIR")"

target="$here/.docker/projects"

# Всё, что не является исходным кодом. Окружение хоста собрано под macOS и в
# Linux-образе бесполезно; базы, выгрузки и логи живут в томах; `samples` и
# `pages` у omarket — сохранённые страницы площадки на сотни мегабайт, нужные
# только при разборе её вёрстки.
#
# Отдельно — секреты. `.env` проектов, ключ сервисного аккаунта Google и
# реквизиты компаний в образ не попадают и попасть не должны: образ уезжает в
# реестр целиком, и вытащить из него слой с ключом может каждый, у кого есть
# доступ к реестру. Всё это подключается томом на запуске — заодно правится
# без пересборки.
exclude=(
  # Перечень отечественных товаров — раньше общего запрета на `.docx`: порядок
  # правил в rsync решает, и без этой строки приказ Минпрома отсекался вместе
  # с тендерными документами. Он не документ закупки, а данные ядра: по нему
  # закупка красится красным, и без него платформа молча перестаёт их
  # отмечать — без ошибки, просто без пометок.
  --include "Перечень_товаров.docx"
  --exclude ".env"
  --exclude ".env.local"
  --exclude "google-service-account.json"
  --exclude "companies.toml"
  --exclude ".venv/"
  --exclude ".git/"
  --exclude "__pycache__/"
  --exclude "*.egg-info/"
  --exclude ".mypy_cache/"
  --exclude ".pytest_cache/"
  --exclude ".ruff_cache/"
  --exclude ".idea/"
  --exclude ".DS_Store"
  --exclude "data/"
  --exclude "exports/"
  --exclude "logs/"
  --exclude "docs/samples/"
  --exclude "docs/pages/"
  --exclude "tests/"
  --exclude "*.xlsx"
  --exclude "*.pdf"
  --exclude "*.docx"
)

copy() {
  local name="$1" source="$2"
  if [ ! -d "$source" ]; then
    # Фигурные скобки обязательны: за именем сразу идёт «»», и bash в UTF-8
    # прихватывает её первый байт в имя переменной. При `set -u` это падение
    # с «unbound variable» вместо сообщения — то есть скрипт ломается ровно
    # там, где должен объяснить, что не так.
    echo "Не найден проект «${name}»: ${source}" >&2
    echo "Укажите путь переменной ${3} — в .env или в команде:" >&2
    echo "    make prod ${3}=../${name}" >&2
    exit 1
  fi
  mkdir -p "$target/$name"
  # `--delete`: удалённый в проекте файл должен исчезнуть и здесь, иначе в
  # образ уедет модуль, которого в проекте уже нет.
  rsync -a --delete "${exclude[@]}" "$(cd "$source" && pwd)/" "$target/$name/"
  echo "  $name  <-  $(cd "$source" && pwd)"
}

echo "Готовлю исходники проектов:"
copy tender-analyze "$TENDER_DIR" TENDER_DIR
copy skstore "$SKSTORE_DIR" SKSTORE_DIR
copy omarket "$OMARKET_DIR" OMARKET_DIR

# Файлы, которые Compose подключает томом поштучно. Проверяются здесь, потому
# что Docker на месте несуществующего пути молча создаёт каталог — и падение
# приходит позже и совсем в другом месте: «IsADirectoryError: companies.toml»
# из недр ядра при обращении к готовности. Найти по такому следу причину
# «файл не доехал на сервер» почти нельзя.
mounted() {
  local path="$1" why="$2"
  if [ -d "$path" ]; then
    echo >&2
    echo "На месте файла — каталог: $path" >&2
    echo "Его создал Docker, когда файла не было при первом запуске." >&2
    echo "    sudo rm -rf \"$path\"   и скопируйте настоящий файл" >&2
    exit 1
  fi
  if [ ! -f "$path" ]; then
    echo >&2
    echo "Нет файла: $path" >&2
    echo "$why" >&2
    echo "Пустой тоже годится — но пустоту надо создать самому, иначе Docker" >&2
    echo "сделает на этом месте каталог: touch \"$path\"" >&2
    exit 1
  fi
}

mounted "$TENDER_DIR/.env" "Настройки тендерного ядра: ключ модели и адрес базы."
mounted "$TENDER_DIR/companies.toml" "Наши юрлица: по ним разбор считает, от кого подаём."
mounted "$SKSTORE_DIR/.env" "Доступы SKStore: без них кабинет не отдаст закупы."
mounted "$OMARKET_DIR/.env" "Доступы OMarket."

echo "Готово: $(du -sh "$target" | cut -f1) в .docker/projects"
