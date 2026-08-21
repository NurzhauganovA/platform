# Запуск платформы в контейнерах.
#
# Один вход вместо трёх шагов. Собрать образ мало: перед сборкой нужно
# перенести в контекст исходники соседних проектов, а после запуска — завести
# первого человека, иначе войти в интерфейс будет некому.
#
#   make up        собрать и поднять всё (машина разработчика, :8080)
#   make prod      то же на сервере: 80 порт, перезапуск при загрузке
#   make logs      смотреть, что происходит
#   make user      завести сотрудника
#   make down      остановить
#
# Каталоги проектов можно переопределить, если раскладка другая:
#
#   make up OMARKET_DIR=~/code/omarket

# Имя набора Compose. По умолчанию — имя каталога, ровно то, что Compose
# подставляет сам, когда `-p` не указан.
#
# Записано явно, но менять его нельзя: под этим именем на сервере уже созданы
# тома. Смена имени не переносит данные — Compose заводит новые пустые тома и
# поднимает поверх них пустую базу, а рабочая остаётся лежать рядом
# невостребованной. Выглядит это как «платформа потеряла все данные».
PROJECT ?= $(notdir $(CURDIR))

COMPOSE ?= docker compose -p $(PROJECT) -f docker-compose.yml -f docker-compose.dev.yml --profile full
# Рабочий режим — тот же набор служб плюс слой отличий сервера.
PROD = docker compose -p $(PROJECT) -f docker-compose.yml -f docker-compose.prod.yml --profile full

# Проверочная среда: тот же слой отличий сервера, но своё имя набора, свои
# порты и своя база. Слой один и тот же намеренно — проверять надо ровно то,
# что потом поднимут в работу; отдельный файл разошёлся бы с рабочим, и
# расхождение обнаружилось бы на рабочем сервере.
#
# Имя набора у проверочной своё и не зависит от каталога: оба дерева
# называются `platform`, и без этого проверочная встала бы поверх рабочей.
# Набор новый, поэтому имя выбирается свободно — томов под ним ещё нет.
STAGE = STACK=fintend-stage WEB_BIND=127.0.0.1 WEB_PORT=$(STAGE_WEB_PORT) POSTGRES_PORT=$(STAGE_PG_PORT) \
	REDIS_PORT=$(STAGE_REDIS_PORT) API_PORT=$(STAGE_API_PORT) \
	docker compose -p fintend-stage -f docker-compose.yml -f docker-compose.prod.yml --profile full

# Порты проверочной среды. Рабочие заняты, и совпадение — это не «не
# поднялось», а «поднялось вместо рабочего».
STAGE_WEB_PORT ?= 8081
STAGE_PG_PORT ?= 5433
STAGE_REDIS_PORT ?= 6380
STAGE_API_PORT ?= 8001
# Пути к подключённым проектам не задаются здесь по умолчанию — умолчания
# лежат в `docker-compose.yml` и в `infra/stage-projects.sh`. Экспортируется
# только то, что человек указал сам:
#
#   make prod OMARKET_DIR=../omarket
#
# Иначе получается ловушка: `export ... ?=` подставляет своё значение всегда,
# оно попадает в окружение и перебивает то, что записано в `.env`, — путь из
# `.env` молча не действует, и сборка не находит проект.
ifdef TENDER_DIR
export TENDER_DIR
endif
ifdef SKSTORE_DIR
export SKSTORE_DIR
endif
ifdef OMARKET_DIR
export OMARKET_DIR
endif

.PHONY: help sources build up prod down restart logs ps user shell migrate check clean backup restore \
	prod-user stage stage-down stage-logs stage-ps stage-user

help:
	@echo "make up       собрать и поднять платформу  ->  http://localhost:8080"
	@echo "make prod     рабочая на сервере            ->  http://bcorp.kz"
	@echo "make stage    проверочная рядом с ней       ->  https://stage.bcorp.kz"
	@echo "make backup   снять копию баз и файлов"
	@echo "make user     завести сотрудника (на своей машине)"
	@echo "              на сервере: make prod-user / make stage-user"
	@echo "make logs     поток журналов"
	@echo "make ps       что запущено"
	@echo "make down     остановить"
	@echo "make clean    остановить и удалить данные платформы"

# Исходники соседних проектов переносятся в контекст сборки: Docker читает
# только то, что лежит внутри него, а проекты лежат снаружи и в разных деревьях.
sources:
	@./infra/stage-projects.sh

build: sources
	@$(COMPOSE) build
	@echo
	@echo "Образы собраны, но контейнеры всё ещё на прежних."
	@echo "Поднять новые: make up"

up: sources
	@test -f .env || { echo "Нет .env — скопируйте .env.example и впишите GEMINI_API_KEY"; exit 1; }
	@$(COMPOSE) up -d --build
	@echo
	@echo "Интерфейс:  http://localhost:8080"
	@echo "API:        http://localhost:8000/api/docs"
	@echo
	@echo "Если входить некем — заведите сотрудника: make user"

# На сервере: 80 порт, журнал строками JSON, перезапуск после перезагрузки.
# Отличия лежат в `docker-compose.prod.yml` — здесь только их подключение.
prod: sources
	@test -f .env || { echo "Нет .env — скопируйте .env.example и впишите ключи"; exit 1; }
	@$(PROD) up -d --build
	@echo
	@echo "Платформа: http://bcorp.kz  (и по адресу самой машины)"
	@echo "Журнал:    make logs"
	@echo
	@echo "Снаружи — через Cloudflare Tunnel. Сертификатов на машине нет,"
	@echo "портов открывать не надо: infra/README.md"

# Проверочная среда. Поднимается из своего дерева со своим `.env`, поэтому
# смотрит в свои базы и свои каталоги проектов: прогон в ней не должен
# дописывать ничего в рабочие данные.
stage: sources
	@test -f .env || { echo "Нет .env — скопируйте .env.example и впишите ключи"; exit 1; }
	@$(STAGE) up -d --build
	@echo
	@echo "Проверочная: https://stage.bcorp.kz  (через Cloudflare Tunnel)"
	@echo "             на самой машине — http://127.0.0.1:$(STAGE_WEB_PORT)"
	@echo "Журнал:      make stage-logs"
	@echo
	@echo "Рабочая среда не тронута: у наборов разные контейнеры, тома и базы."
	@echo "Убедились, что работает — тогда в рабочем дереве: git pull && make prod"

stage-down:
	@$(STAGE) down

stage-logs:
	@$(STAGE) logs -f --tail=80 api worker

stage-ps:
	@$(STAGE) ps

stage-user:
	@$(STAGE) run --rm --no-deps api $(create-user)

# Копия баз и файлов. Держать её на том же диске бессмысленно — пожар и
# шифровальщик забирают оба; `infra/backup.sh` кладёт рядом, увозить надо
# отдельно.
backup:
	@./infra/backup.sh

down:
	@$(COMPOSE) down

restart:
	@$(COMPOSE) restart api worker

logs:
	@$(COMPOSE) logs -f --tail=80 api worker

ps:
	@$(COMPOSE) ps

# Заводится в контейнере, а не с машины: пароль хэшируется тем же кодом, что
# его потом проверяет, и база у них одна.
#
# Цель своя на каждую среду, и это не многословие ради стройности. Раньше
# команда шла без указания файлов — Compose брал имя набора от каталога и
# заводил третий, `platform`: одноразовый контейнер поднимался в сети, где
# базы нет, и сотрудник не заводился нигде. Промолчать тут нельзя, а угадать
# среду по окружению — значит однажды угадать не ту.
define create-user
	python -m platform_api.cli create-user \
		--email $(or $(EMAIL),analyst@fintend.kz) \
		--org $(or $(ORG),fintend) \
		--org-name "$(or $(ORG_NAME),Fintend)" \
		--role $(or $(ROLE),analyst) \
		--name "$(or $(NAME),Тендерщик)"
endef

user:
	@$(COMPOSE) run --rm --no-deps api $(create-user)

prod-user:
	@$(PROD) run --rm --no-deps api $(create-user)

shell:
	@$(COMPOSE) exec api bash

migrate:
	@$(COMPOSE) run --rm --no-deps -w /app/apps/api api alembic upgrade head

# Готовность модулей глазами самой платформы: что настроено, чего не хватает.
check:
	@curl -fsS http://localhost:8000/api/health | python3 -m json.tool

# Удаляет тома платформы: базу, очередь и загруженные папки. Базы подключённых
# проектов лежат на машине и остаются нетронутыми.
clean:
	@$(COMPOSE) down -v
