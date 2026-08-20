# Образ интерфейса: сборка Vite и раздача статики nginx.
#
# Собранный фронтенд — это набор файлов, и держать под ним Node незачем: в
# готовом образе остаётся только nginx с сотней килобайт статики. Заодно
# исчезает целый слой того, что могло бы выполниться на сервере.
#
# Контекст сборки — каталог `apps/web`.

FROM node:22-alpine AS build

WORKDIR /src

# Сначала манифесты: слой с установкой пакетов переживает правку кода.
COPY package.json package-lock.json* ./
# `npm ci` вместо `install`: ставит ровно то, что записано в замке. Иначе
# сборка в разное время даёт разные зависимости, и «у меня работало»
# становится честным ответом.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
