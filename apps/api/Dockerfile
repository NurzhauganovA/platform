# Образ платформы: веб и исполнитель очереди.
#
# Две цели из одного файла. Код у них общий — разными их делает браузер:
# исполнителю он нужен, чтобы забирать предзаказы из кабинета OMarket, а веб
# в браузер не ходит никогда, и таскать в нём триста мегабайт Chromium незачем.
#
# Подключённые проекты ставятся editable, и это не привычка из разработки.
# Каждый из них вычисляет свой корень от расположения файла — оттуда он берёт
# свой `.env`, свою базу и каталог выгрузок. Обычная установка положила бы их
# в `site-packages`, и корнем оказалась бы папка библиотек Python: настройки и
# база искались бы там, где их никогда не будет.
#
# Контекст сборки — корень платформы. Исходники соседних проектов кладёт туда
# `infra/stage-projects.sh`: они лежат вне этого каталога, а Docker читает
# только то, что внутри контекста.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `unar` распаковывает rar: тендерные папки приходят архивами, и без него
# разбор останавливается на первом же. Остальные форматы закрыты колёсами.
# `curl` нужен проверке живости — без него healthcheck пришлось бы писать на
# Python и поднимать интерпретатор раз в полминуты.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unar curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app


FROM base AS deps

# Сначала только описания зависимостей. Слой с установкой переживает правку
# кода: меняется он, лишь когда меняется список пакетов, а не каждый раз,
# когда поправили обработчик.
COPY apps/api/pyproject.toml apps/api/README.md ./apps/api/
COPY .docker/projects/tender-analyze/pyproject.toml ./projects/tender-analyze/
COPY .docker/projects/skstore/pyproject.toml ./projects/skstore/
COPY .docker/projects/omarket/pyproject.toml ./projects/omarket/

# Пустые пакеты, чтобы установка зависимостей прошла до появления исходников.
RUN mkdir -p apps/api/src/platform_api \
      projects/tender-analyze/src/tender_analyze \
      projects/skstore/src/skstore \
      projects/omarket/src/omarket \
    && touch apps/api/src/platform_api/__init__.py \
      projects/tender-analyze/src/tender_analyze/__init__.py \
      projects/skstore/src/skstore/__init__.py \
      projects/omarket/src/omarket/__init__.py \
    && for project in projects/*/; do touch "$project/README.md"; done

RUN pip install --upgrade pip \
    && pip install \
        -e ./apps/api \
        -e ./projects/tender-analyze \
        -e ./projects/skstore \
        -e ./projects/omarket


FROM deps AS app

# Теперь настоящий код. Проекты — в `/app/projects/<имя>`, и корень каждого
# из них внутри контейнера именно такой: туда подключаются `.env` и базы.
COPY .docker/projects/tender-analyze/ ./projects/tender-analyze/
COPY .docker/projects/skstore/ ./projects/skstore/
COPY .docker/projects/omarket/ ./projects/omarket/
COPY apps/api/ ./apps/api/

# Каталоги, которые проекты создают у себя сами. Если их не завести заранее,
# первый же запуск упрётся в права: работаем не от root.
RUN mkdir -p storage projects/tender-analyze/data projects/skstore/data \
      projects/omarket/data projects/skstore/exports projects/omarket/exports \
      projects/tender-analyze/exports projects/tender-analyze/logs

# Не от root. Процесс ходит в интернет и разбирает присланные файлы — ровно
# то место, где чужой код однажды выполнится, и делать это администратором
# необязательно.
RUN useradd --create-home --uid 10001 fintend \
    && chown -R fintend:fintend /app
USER fintend


FROM app AS api

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/health >/dev/null || exit 1

CMD ["python", "-m", "platform_api"]


FROM app AS worker

# Chromium только здесь. Кабинет OMarket закрыт защитой от автоматизации:
# запросы делает сама страница, а мы читаем ответы, — поэтому выгрузка
# предзаказов идёт настоящим браузером. Вход по ЭЦП при этом остаётся на
# машине сотрудника: ключ лежит у него, и там ему и место. Контейнер работает
# с сессией, снятой командой `omarket login`.
#
# Общий каталог вместо домашнего кэша: иначе браузер скачивается в кэш root, а
# работаем мы не от него, и его пришлось бы копировать второму пользователю —
# полтора гигабайта одного и того же в двух слоях.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

USER root
# Пакет playwright уже стоит зависимостью omarket — здесь только браузер.
# `--with-deps` тянет системные библиотеки через apt, и списки после него надо
# убрать в том же слое, иначе они останутся в образе навсегда.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chown -R fintend:fintend "$PLAYWRIGHT_BROWSERS_PATH"
USER fintend

CMD ["python", "-m", "platform_api.jobs.worker"]
