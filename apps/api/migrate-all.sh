#!/usr/bin/env bash
#
# Приводит в порядок все базы разом: платформы и трёх подключённых ядер.
#
# Запускается службой `migrate` до старта API. Раньше здесь стояло одно
# `alembic upgrade head` — только для платформы, — и на чистом сервере это
# выглядело так: интерфейс открывается, разделы пусты. Потому что `POSTGRES_DB`
# создаёт ровно одну базу, а соседние три на машине разработчика заводились
# руками и в развёртывании не значились.
#
# Идемпотентно: повторный запуск ничего не портит, поэтому вызывается при
# каждом `make prod` и `make up`.

set -euo pipefail

# Ядра держат схемы у себя: у каждого свои миграции и своя история. Общая
# схема означала бы, что правка в одном проекте ломает соседа.
#
# Четвёртое поле — чем схему поднимать. У платформы, skstore и omarket это
# alembic; у tender-analyze миграций нет вовсе, он создаёт таблицы командой
# `init-db`. Вызывать его alembic'ом значит молча пропустить базу и получить
# пустой раздел тендеров — ровно то, с чего этот скрипт и начался.
projects=(
  "платформа:/app/apps/api:PLATFORM__DB__URL:alembic"
  "tender-analyze:/app/projects/tender-analyze:TENDER__DB__URL:tender_analyze"
  "skstore:/app/projects/skstore:SKSTORE__DB__URL:alembic"
  "omarket:/app/projects/omarket:OMARKET__DB__URL:alembic"
)

# Базы создаются здесь, а не в `docker-entrypoint-initdb.d`: тот отрабатывает
# только на пустом томе. Сервер, поднятый до появления этого файла, так бы и
# остался с одной базой — а понять это по пустым разделам непросто.
python - "${projects[@]}" <<'PY'
import os
import sys
from urllib.parse import urlsplit

import psycopg

wanted = []
for item in sys.argv[1:]:
    # Полей четыре: имя, путь, переменная, способ. Разбор на три склеивал бы
    # переменную со способом, `os.environ` не находил бы её — и база молча не
    # создавалась, а падало потом на миграциях.
    _name, _path, variable, _how = item.split(":", 3)
    url = os.environ.get(variable)
    if url:
        wanted.append((variable, url))

for variable, url in wanted:
    parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://"))
    database = parts.path.lstrip("/")
    if not database:
        continue
    # Подключаемся к служебной базе: к несуществующей не подключиться, а
    # `CREATE DATABASE` в PostgreSQL нельзя выполнить внутри транзакции.
    root = parts._replace(path="/postgres").geturl()
    with psycopg.connect(root, autocommit=True) as connection:
        exists = connection.execute(
            "select 1 from pg_database where datname = %s", (database,)
        ).fetchone()
        if exists:
            print(f"  {database} — есть")
            continue
        connection.execute(f'create database "{database}"')
        print(f"  {database} — создана")
PY

for item in "${projects[@]}"; do
  IFS=':' read -r name path variable how <<< "$item"

  if [ -z "${!variable:-}" ]; then
    echo "  ${name}: не задан ${variable}, пропущено"
    continue
  fi

  if [ "$how" = "alembic" ]; then
    if [ ! -f "$path/alembic.ini" ]; then
      echo "  ${name}: нет alembic.ini — схему поднять нечем" >&2
      exit 1
    fi
    echo "  ${name}: миграции"
    (cd "$path" && alembic upgrade head)
  else
    # `init-db` создаёт недостающие таблицы и не трогает существующие, так
    # что повторный запуск безопасен.
    echo "  ${name}: init-db"
    (cd "$path" && python -m "$how" init-db)
  fi
done

echo "Схемы готовы."
