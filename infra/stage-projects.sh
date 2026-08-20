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

TENDER_DIR="${TENDER_DIR:-$here/../tender-analyze}"
SKSTORE_DIR="${SKSTORE_DIR:-$here/../skstore}"
OMARKET_DIR="${OMARKET_DIR:-$here/../omarket}"

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
    echo "Не найден проект «$name»: $source" >&2
    echo "Укажите путь переменной ${3}, если каталог лежит в другом месте." >&2
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

echo "Готово: $(du -sh "$target" | cut -f1) в .docker/projects"
