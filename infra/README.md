# Развёртывание на сервере

Платформа отвечает на `bcorp.kz` по 80 порту. Ниже — что сделать на чистой
машине и в каком порядке.

## Прежде чем открывать наружу

**Сейчас платформа работает по HTTP.** Пароль при входе и кука сессии идут
открытым текстом: кто угодно в той же сети видит их целиком, а за этой кукой
лежат себестоимость, маржа и КП конкурентов. В офисной сети это терпимо; как
только `bcorp.kz` начнёт отвечать из интернета — нет.

Место под сертификат в конфигурации уже есть
(`/.well-known/acme-challenge/`), включение не требует правки файлов:

```bash
docker run --rm -v platform_certbot:/var/www/certbot \
  -v /etc/letsencrypt:/etc/letsencrypt certbot/certbot \
  certonly --webroot -w /var/www/certbot -d bcorp.kz -d www.bcorp.kz
```

После выпуска в `apps/web/nginx.conf` добавляется блок на 443 и перенос с 80,
а `docker-compose.prod.yml` подключает `/etc/letsencrypt`. Скажите — сделаю.

## Что нужно на сервере

- Ubuntu Server 24.04 LTS, диски в зеркале
- Docker Engine и плагин Compose из официального репозитория Docker
- `git`, `make`
- Постоянный адрес и запись `bcorp.kz` → адрес сервера в DNS
- Открыты 80 и 22, остальное закрыто

## Порядок

### 1. Репозитории

Собирается образ из четырёх деревьев: платформа плюс три подключённых
проекта. Они ставятся editable, поэтому нужны исходники, а не пакеты.

```bash
sudo mkdir -p /srv/fintend && sudo chown "$USER" /srv/fintend && cd /srv/fintend
git clone <platform> platform
git clone <tender-analyze> tender-analyze
git clone <skstore> skstore
git clone <omarket> omarket
```

Раскладка по умолчанию ждёт `tender-analyze` и `skstore` рядом с `platform`, а
`omarket` — на два уровня выше. На сервере проще положить всё рядом и сказать
об этом явно:

```bash
cd platform
echo 'OMARKET_DIR=../omarket' >> .env
```

### 2. Настройки и ключи

```bash
cp .env.example .env
```

Заполнить: `GEMINI_API_KEY`, `PLATFORM__SECRET_KEY`, `TENDER_ARCHIVE`.

`TENDER_ARCHIVE` — путь к архиву тендерных папок **на этой машине**. Он
подключается в контейнер тем же путём: в базе ядра лежат абсолютные пути
документов, и другое место потребовало бы переписывать их на лету.

У подключённых проектов свои `.env` — они читаются из их каталогов. Базы там
задавать не нужно: адреса прописаны в `docker-compose.yml` и смотрят на
соседние базы того же PostgreSQL.

### 3. Первый запуск

```bash
make prod
```

Соберёт образы, поднимет базу, очередь, API, исполнителя и nginx, применит
миграции платформы. Дальше — схемы подключённых ядер:

```bash
docker compose exec api bash -lc 'cd /app/projects/tender-analyze && alembic upgrade head'
docker compose exec api bash -lc 'cd /app/projects/skstore && alembic upgrade head'
docker compose exec api bash -lc 'cd /app/projects/omarket && alembic upgrade head'
```

### 4. Данные

На прежней машине:

```bash
make backup                      # снимет четыре базы и загруженные файлы
scp -r backups/<дата> сервер:/srv/fintend/platform/backups/
rsync -a ~/Desktop/тендеры/ сервер:/srv/fintend/тендеры/
```

На сервере:

```bash
./infra/restore.sh backups/<дата>
./infra/repath.sh /srv/fintend/тендеры
```

`repath.sh` переписывает абсолютные пути документов в базе ядра под путь
архива на сервере. Без этого список файлов в разборе виден, а открыть их
нельзя: платформа ищет их там, где они лежали на машине тендерщика.

### 5. Сотрудники

```bash
make user EMAIL=ivanov@bcorp.kz ROLE=analyst NAME="Иванов Иван"
```

Роли: `admin`, `analyst` (тендерщик — видит деньги), `buyer` (закупщик — видит,
где взять товар, но не себестоимость), `viewer`.

### 6. Копии

```bash
crontab -e
```

```
30 2 * * * cd /srv/fintend/platform && ./infra/backup.sh >> /var/log/fintend-backup.log 2>&1
```

Скрипт сам проверяет, что дампы читаются, и убирает копии старше двух недель.

**Копия рядом с сервером — не копия.** Пожар, залив и кража забирают машину
вместе с диском в ней. Раз в неделю копию надо увозить: внешний диск,
NAS в другом здании или облачное хранилище — что угодно, лишь бы не здесь.

Раз в квартал — проверочное восстановление на отдельную базу. Копия, которую
ни разу не разворачивали, — это надежда, а не копия.

## Что дальше

```bash
make logs                # поток журналов API и исполнителя
make ps                  # что запущено
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile full restart api
```

Обновление платформы: `git pull && make prod`. Образы пересобираются, тома с
данными остаются.

## Чего здесь пока нет

- **HTTPS** — см. выше. Первое, что надо сделать перед выходом наружу.
- **Расписание прогонов.** Почасовые разборы skstore и omarket пока
  запускаются кнопкой: планировщика в платформе нет.
- **Мониторинг.** Об упавшем исполнителе узнаёт тот, кто заметил, что задачи
  не идут.
