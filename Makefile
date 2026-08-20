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

COMPOSE ?= docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile full
# Рабочий режим — тот же набор служб плюс слой отличий сервера.
PROD = docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile full
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

.PHONY: help stage build up prod down restart logs ps user shell migrate check clean backup restore

help:
	@echo "make up       собрать и поднять платформу  ->  http://localhost:8080"
	@echo "make prod     то же на сервере               ->  http://bcorp.kz"
	@echo "make backup   снять копию баз и файлов"
	@echo "make user     завести сотрудника"
	@echo "make logs     поток журналов"
	@echo "make ps       что запущено"
	@echo "make down     остановить"
	@echo "make clean    остановить и удалить данные платформы"

# Исходники соседних проектов переносятся в контекст сборки: Docker читает
# только то, что лежит внутри него, а проекты лежат снаружи и в разных деревьях.
stage:
	@./infra/stage-projects.sh

build: stage
	@$(COMPOSE) build
	@echo
	@echo "Образы собраны, но контейнеры всё ещё на прежних."
	@echo "Поднять новые: make up"

up: stage
	@test -f .env || { echo "Нет .env — скопируйте .env.example и впишите GEMINI_API_KEY"; exit 1; }
	@$(COMPOSE) up -d --build
	@echo
	@echo "Интерфейс:  http://localhost:8080"
	@echo "API:        http://localhost:8000/api/docs"
	@echo
	@echo "Если входить некем — заведите сотрудника: make user"

# На сервере: 80 порт, журнал строками JSON, перезапуск после перезагрузки.
# Отличия лежат в `docker-compose.prod.yml` — здесь только их подключение.
prod: stage
	@test -f .env || { echo "Нет .env — скопируйте .env.example и впишите ключи"; exit 1; }
	@$(PROD) up -d --build
	@echo
	@echo "Платформа: http://bcorp.kz  (и по адресу самой машины)"
	@echo "Журнал:    make logs"
	@echo
	@echo "Пока платформа отвечает по HTTP, пароли и куки идут открытым"
	@echo "текстом. Прежде чем открывать её наружу — HTTPS: infra/README.md"

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
user:
	@docker compose --profile full run --rm --no-deps api \
		python -m platform_api.cli create-user \
		--email $(or $(EMAIL),analyst@fintend.kz) \
		--org $(or $(ORG),fintend) \
		--org-name "$(or $(ORG_NAME),Fintend)" \
		--role $(or $(ROLE),analyst) \
		--name "$(or $(NAME),Тендерщик)"

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
