# Развёртывание на сервере (Docker Compose)

## Требования

- Docker Engine + плагин Docker Compose (`docker compose version` должен работать).
- Открытые порты на сервере: **80** (API + Swagger), **9000** (MinIO, ссылки на файлы).

## Шаги

```bash
# 1. Склонировать проект на сервер
git clone <repo-url> && cd InsurancePlatformPy

# 2. Создать .env из шаблона и заменить ВСЕ значения change-me
cp .env.example .env
nano .env

# 3. Собрать и запустить весь стек
docker compose up -d --build

# 4. Проверить, что всё поднялось
docker compose ps          # app должен быть healthy, alembic — exited (0)
docker compose logs app    # логи приложения
```

Миграции применяются автоматически: сервис `alembic` выполняет
`alembic upgrade head` после готовности базы, и только после его успешного
завершения стартует `app`.

## Проверка Swagger

- Swagger UI: `http://<IP-сервера>/docs` (или `http://<IP-сервера>:8000/docs`)
- ReDoc: `http://<IP-сервера>/redoc`
- OpenAPI-схема: `http://<IP-сервера>/openapi.json`

## Первичный владелец (один раз после первого запуска)

```bash
docker compose exec app uv run --no-sync python -m scripts.init_owner
```

Логин/пароль берутся из `OWNER_LOGIN` / `OWNER_PASSWORD` в `.env`.
Скрипт идемпотентен — повторный запуск ничего не сломает.

## Что куда смотрит

| Сервис   | Порт снаружи         | Назначение                                  |
|----------|----------------------|---------------------------------------------|
| app      | 80, 8000             | FastAPI + Swagger                           |
| minio    | 9000                 | Файлы (presigned-ссылки)                    |
| minio    | 127.0.0.1:9001       | Консоль MinIO (только с самого сервера)     |
| database | 127.0.0.1:5432       | Postgres (только с самого сервера)          |
| redis    | 127.0.0.1:6379       | Redis (только с самого сервера)             |

Postgres, Redis и консоль MinIO наружу не опубликованы — доступ к ним только
через SSH-туннель или с самого сервера.

## Важно про MinIO и ссылки на файлы

Presigned-ссылки на сертификаты/файлы генерируются с хостом из
`MINIO_ENDPOINT`. Значение по умолчанию `minio:9000` работает только внутри
docker-сети. Если ссылки должны открываться у внешних клиентов, укажите в
`.env`:

```
MINIO_ENDPOINT=<IP-сервера>:9000
```

## Обновление

```bash
git pull
docker compose up -d --build   # пересборка + повторный прогон миграций
```
