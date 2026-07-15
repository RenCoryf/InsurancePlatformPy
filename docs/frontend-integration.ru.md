# Интеграция фронтенда с Python REST (чат-сервер)

Документ для фронтенд-команды. Описывает REST-контракт Python-бэкенда,
который обслуживает чат: выдача токенов, список чатов, история, файлы,
дашборд саппорта, админка.

Парный документ — `InsurancePlatform/docs/frontend-integration.ru.md` —
описывает WebSocket-шлюз `chatgw` (Go), через который ходят живые
сообщения. Здесь — про всё, что **не** WebSocket.

## 1. Где что лежит

| Что                          | Кто отвечает  | Куда обращаться                                  |
|------------------------------|---------------|--------------------------------------------------|
| Открыть/закрыть сессию (live)| Go gateway    | `ws://chatgw/ws` (см. парный документ)           |
| Отправить сообщение/файл     | Go gateway    | WebSocket-кадр (см. парный документ)             |
| Получать сообщения в реальном времени | Go gateway | WebSocket fanout (см. парный документ)        |
| Логин пользователя           | Python REST   | `POST /api/v1/auth/login/` (существующий)        |
| Логин саппорта               | Python REST   | `POST /api/v1/support/login/`                    |
| Список своих чатов           | Python REST   | `GET  /api/v1/chats/`                            |
| Открыть бонусный чат         | Python REST   | `POST /api/v1/chats/`                            |
| История сообщений            | Python REST   | `GET  /api/v1/chats/{chat_id}/messages/`         |
| Загрузить файл               | Python REST   | `POST /api/v1/files/`                            |
| Скачать файл                 | Python REST   | `GET  /api/v1/files/{file_id}/`                  |
| Список активных чатов (саппорт) | Python REST | `GET  /api/v1/support/chats/`                    |
| CRUD саппорт-агентов         | Python REST   | `/api/v1/admin/support-agents/` (JWT админа)     |

База URL: например, `https://api.example.com` для прода и
`http://localhost:8000` локально (см. `scripts/run-dev.sh`).

## 2. Аутентификация

Везде в `/api/v1/*` — `Authorization: Bearer <JWT>`. Для `/api/v1/admin/*` нужен
JWT саппорт-агента с ролью `admin` (получается через `/api/v1/support/login/`).
Токены HS256, время жизни access-токена — 15 минут по умолчанию.

### 2.1 Пользовательский JWT

Получается через существующий SMS-flow:

```
POST /api/v1/auth/request-code/  { "phone": "+7..." }
POST /api/v1/auth/register/      { "phone", "code", "email", "password", "referral_code", ... }
POST /api/v1/auth/login/         { "phone", "code" }
```

В полезной нагрузке access-токена (информационно — фронтенду парсить не
нужно, проверкой занимаются gateway и REST):

```json
{
  "user_id": 42,
  "sub": "user:42",
  "role": "user",
  "type": "access",
  "exp": 1779322487,
  "iat": 1779321587
}
```

### 2.2 Саппорт-JWT

Саппорт-агентов создаёт админ (раздел 7). Пользовательского SMS-flow у
них нет — отдельный endpoint логина:

```
POST /api/v1/support/login/

Request:
{
  "login":    "alice",
  "password": "..."
}

Response 200:
{
  "access_token": "eyJ...",
  "token_type":   "bearer",
  "expires_in":   900
}
```

Полезная нагрузка содержит `sub: "support:<id>"` и `role: "support"`.
Refresh-токенов для саппорта в v1 нет — после истечения access нужно
залогиниться заново.

Ошибки:
- `401 Unauthorized` — неверный логин/пароль или агент деактивирован.

### 2.3 Какие endpoints доступны какому субъекту

| Endpoint                                | Юзер | Саппорт | Внешний (Go) | Админ (JWT)   |
|-----------------------------------------|------|---------|--------------|---------------|
| `/api/v1/auth/*` (existing)             | ✓    | —       | —            | —             |
| `/api/v1/support/login/`                | —    | (анон.) | —            | —             |
| `/api/v1/chats/` (GET/POST)             | ✓    | —       | —            | —             |
| `/api/v1/chats/{id}/messages/`          | ✓ (только свой чат) | ✓ | — | — |
| `/api/v1/files/`                        | ✓    | ✓       | —            | —             |
| `/api/v1/files/{id}/`                   | ✓ (участник чата) | ✓ | — | —          |
| `/api/v1/support/chats/`                | —    | ✓       | —            | —             |
| `/api/v1/admin/support-agents/*`        | —    | —       | —            | ✓             |
| `/internal/*`                           | —    | —       | ✓            | —             |

## 3. Чаты

У каждого пользователя ровно два чата:

- **`main`** — основной (про сделки). Создаётся лениво при первом
  обращении к чатам. Всегда существует после первого `GET /api/v1/chats/`.
- **`bonus`** — бонусный. Создаётся, когда пользователь его явно
  открывает (раздел 3.2). Может не существовать.

Оба — 1-на-1 с саппортом (любой активный саппорт-агент видит чат и может
отвечать).

### 3.1 `GET /api/v1/chats/` — список своих чатов

Авторизация: пользовательский JWT.

Response 200:

```json
[
  {
    "id":              "11111111-1111-1111-1111-111111111111",
    "type":            "main",
    "last_message_at": "2026-05-21T00:03:53.536603Z"
  },
  {
    "id":              "22222222-2222-2222-2222-222222222222",
    "type":            "bonus",
    "last_message_at": null
  }
]
```

`last_message_at` — `null`, если в чате ещё нет сообщений.

Если пользователь раньше никогда не обращался к чатам — этот вызов
**сам создаст** `main` (UNIQUE-констрейнт гарантирует, что параллельные
вызовы не сделают дубликата). `bonus` лениво не создаётся — для него
нужен явный POST.

### 3.2 `POST /api/v1/chats/` — открыть чат явно

Авторизация: пользовательский JWT.

Request:

```json
{ "type": "bonus" }
```

`type` ∈ `{"main", "bonus"}`. Идемпотентно: если чат уже существует —
вернётся тот же. Используется фронтендом в момент, когда пользователь
впервые кликает «бонусный чат».

Response 200:

```json
{
  "id":              "22222222-2222-2222-2222-222222222222",
  "type":            "bonus",
  "last_message_at": null
}
```

### 3.3 `GET /api/v1/chats/{chat_id}/messages/` — история сообщений

Авторизация: пользовательский JWT (только свой чат) или саппорт-JWT
(любой чат).

Query-параметры:

| Параметр | Тип    | По умолчанию | Описание                                              |
|----------|--------|--------------|-------------------------------------------------------|
| `limit`  | number | 50           | 1..100                                                |
| `before` | UUID   | —            | Курсор: id того сообщения, **до** которого выдавать  |

Response 200:

```json
{
  "messages": [
    {
      "id":            "...",
      "chat_id":       "...",
      "user_id":       "user:42",
      "role":          "user",
      "kind":          "message",
      "body":          "Привет",
      "client_msg_id": "cm-...",
      "created_at":    "2026-05-21T00:03:53.5Z"
    },
    {
      "id":            "...",
      "chat_id":       "...",
      "user_id":       "support:1",
      "role":          "support",
      "kind":          "file",
      "file": {
        "file_id": "...",
        "name":    "report.pdf",
        "mime":    "application/pdf",
        "size":    12345,
        "url":     "/api/v1/files/.../"
      },
      "client_msg_id": "cm-...",
      "created_at":    "2026-05-21T00:04:01.2Z"
    }
  ],
  "next_cursor": "33333333-3333-3333-3333-333333333333"
}
```

Сообщения отсортированы по `created_at DESC, id DESC` — **сначала
новые**. Для бесконечной прокрутки:

1. Запросите первую страницу без `before`.
2. Если `next_cursor !== null`, для следующей страницы передайте
   `?before=<next_cursor>`.
3. Когда `next_cursor === null` — конец истории, выше нет.

Ответ 403 — если пользователь запросил чужой чат. Ответ 404 — если
`chat_id` не существует.

**Формат `message`** — тот же канонический объект, который приходит по
WebSocket. Поля идентичны (см. раздел 5 в парном документе).

## 4. Файлы

Файл сначала загружается отдельным REST-вызовом — фронтенд получает
`file_id`, после чего шлёт его в gateway во `send_file`-кадре. По
WebSocket байты файлов **не ходят**.

### 4.1 `POST /api/v1/files/` — загрузить файл

Авторизация: пользовательский JWT или саппорт-JWT (нужно быть участником
чата).

Content-Type: `multipart/form-data`.

Поля формы:

| Поле     | Тип   | Описание                              |
|----------|-------|---------------------------------------|
| `file`   | File  | Сам файл                              |
| `chat_id`| UUID  | id чата, в который файл будет привязан|

Ограничения: размер не более `MAX_FILE_BYTES` (по умолчанию 25 МБ).
MIME — без allowlist в v1.

Response 201:

```json
{
  "file_id": "44444444-4444-4444-4444-444444444444",
  "name":    "report.pdf",
  "mime":    "application/pdf",
  "size":    12345,
  "url":     "/api/v1/files/44444444-4444-4444-4444-444444444444/"
}
```

После этого фронтенд отправляет в gateway:

```json
{
  "type":          "send_file",
  "client_msg_id": "cm-...",
  "file_id":       "44444444-4444-4444-4444-444444444444"
}
```

Если попытаться `send_file` с чужим/несвязанным `file_id` — gateway
вернёт `error` с `code: "validation"`, `reason: "file not in chat"`.

Ошибки upload:

| Статус | Причина                                          |
|--------|--------------------------------------------------|
| 403    | Запрашивающий не участник `chat_id`              |
| 404    | `chat_id` не существует                          |
| 413    | Превышен `MAX_FILE_BYTES`                        |

### 4.2 `GET /api/v1/files/{file_id}/` — скачать файл

Авторизация: пользовательский JWT (участник чата файла) или саппорт-JWT.

Ответ — поток байтов с заголовками:

```
Content-Type:        <mime>             (как было загружено)
Content-Length:      <size>
Content-Disposition: inline; filename="<name>"
Cache-Control:       private, max-age=0
```

Для отображения изображений или PDF прямо в браузере достаточно
`<img src="/api/v1/files/{id}/">`/`<embed src=…>` — `Content-Disposition: inline`.

Range-запросы (`Range: bytes=…`) в v1 **не поддерживаются**. Если нужно
докачивать большие файлы — это в бэклоге.

Ошибки:

| Статус | Причина                                          |
|--------|--------------------------------------------------|
| 403    | Не участник чата файла                           |
| 404    | Файл удалён или не существует                    |

## 5. Дашборд саппорта

### 5.1 `GET /api/v1/support/chats/` — список активных чатов

Авторизация: саппорт-JWT.

Query-параметры:

| Параметр        | Тип       | По умолчанию | Описание                                       |
|-----------------|-----------|--------------|------------------------------------------------|
| `type`          | string    | —            | Фильтр: `main` или `bonus`. Без — все.        |
| `limit`         | number    | 50           | 1..200                                         |
| `before`        | ISO-дата  | —            | Курсор по `last_message_at`                    |
| `include_empty` | boolean   | false        | Показывать ли чаты, в которых ещё нет сообщений |

Response 200:

```json
{
  "chats": [
    {
      "id":   "...",
      "type": "main",
      "owner": {
        "id":         42,
        "phone":      "+7...",
        "first_name": "Иван",
        "last_name":  "Иванов"
      },
      "last_message_at": "2026-05-21T00:03:53.5Z"
    }
  ],
  "next_cursor": "2026-05-20T22:11:00.0Z"
}
```

Чаты отсортированы по `last_message_at DESC NULLS LAST` — сначала самые
свежие, в конце — пустые (если включены).

Пагинация: `?before=<next_cursor>` для следующей страницы.

После того как саппорт выбрал чат — он подключается к WebSocket-gateway
с `?type=<тип>&chat_id=<выбранный uuid>` и пользовательским JWT (его
собственным, саппорт-JWT).

## 6. Админка

JWT саппорт-агента с ролью `admin`: `Authorization: Bearer <JWT>` из
`/api/v1/support/login/`. Первый администратор-владелец создаётся скриптом
`scripts/init_owner.py` (логин/пароль из `OWNER_LOGIN` / `OWNER_PASSWORD`).
Прочие менеджеры/админы приглашаются через `POST /api/v1/admin/managers/`
(SMS-инвайт, установка пароля по `/api/v1/support/invite/accept/`).

### 6.1 `POST /api/v1/admin/support-agents/` — создать агента

Request:

```json
{
  "login":        "alice",
  "password":     "min8chars",
  "display_name": "Алиса"
}
```

Response 201:

```json
{
  "id":           1,
  "login":        "alice",
  "display_name": "Алиса",
  "is_active":    true,
  "created_at":   "2026-05-21T00:00:00Z"
}
```

Ошибка 409 — `login` уже занят.

### 6.2 `GET /api/v1/admin/support-agents/`

Query: `?active_only=true&limit=50&offset=0`.

Response 200:

```json
{ "agents": [ { "id": 1, "login": "alice", ... } ] }
```

### 6.3 `PATCH /api/v1/admin/support-agents/{id}/`

Любое подмножество полей:

```json
{
  "password":     "newpass8+",
  "display_name": "Алиса I.",
  "is_active":    false
}
```

Ответ — обновлённый объект агента.

### 6.4 `DELETE /api/v1/admin/support-agents/{id}/`

Soft-delete (выставляет `is_active=false`). Возвращает 204.

## 7. Формат ошибок

### Публичные `/api/v1/*` endpoints

Стандарт FastAPI:

```json
{ "detail": "human-readable message" }
```

или для validation-ошибок (HTTP 422):

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc":  ["body", "email"],
      "msg":  "value is not a valid email address: ...",
      "input": "..."
    }
  ]
}
```

### Внутренние `/internal/*` endpoints

Используются только Go gateway, фронтенд их **не дёргает**. Формат
`{code, reason}` — он же транслируется в WebSocket-кадр `type: "error"`
(см. парный документ, раздел 6).

## 8. Связка с WebSocket gateway

Типовой пользовательский флоу:

```text
1. POST /api/v1/auth/login/        → JWT
2. GET  /api/v1/chats/             → [{ id, type, last_message_at }, ...]
3. GET  /api/v1/chats/{id}/messages/ → история (для подгрузки в UI)
4. WS   /ws?type=main              → подписка на live-фидинг
5. … (юзер пишет сообщение)
6. WS send_message                 → ответ через WS (broadcast)
7. … (юзер хочет отправить файл)
8. POST /api/v1/files/             → file_id
9. WS send_file { file_id }        → ответ через WS (broadcast)
```

Для саппорт-флоу первые шаги другие:

```text
1. POST /api/v1/support/login/       → саппорт JWT
2. GET  /api/v1/support/chats/       → список активных чатов
3. (саппорт кликает один)
4. GET  /api/v1/chats/{id}/messages/ → история
5. WS   /ws?type=main&chat_id=<id>   → подписка
6. … (далее идентично)
```

## 9. Что НЕ делает Python REST

- Не отправляет сообщения за пользователя. `POST /chats/{id}/messages/`
  существовал в скелетной версии, но удалён — все сообщения идут через
  gateway по WebSocket.
- Не отдаёт presigned URLs для файлов. Файлы скачиваются через сам
  Python (streaming).
- Не имеет `mark as read`, unread-счётчиков, typing-индикаторов и
  presence в v1.
- Не имеет refresh-токенов для саппорта.

Эти пункты — в бэклоге; если что-то из них критично — поднимайте отдельно.

## 10. Локальная разработка

Один скрипт поднимает весь стек:

```bash
cd InsurancePlatformPy
./scripts/run-dev.sh
```

Поднимает postgres + minio, накатывает миграции, создаёт MinIO-bucket,
стартует Python (`:8000`) и Go chatgw (`:8080`). Ctrl-C — корректное
выключение обоих серверов.

URLs для разработки:

- Python REST: `http://localhost:8000`
- Go gateway:  `ws://localhost:8080/ws`
- MinIO console: `http://localhost:9001` (логин/пароль `minioadmin/minioadmin`)
- OpenAPI / Swagger: `http://localhost:8000/docs`

## 11. Изменения протокола

Если меняется форма какого-либо ответа, нужны одновременные правки:

- `app/api/routers/*` и `app/models/dto/*` — Python;
- `docs/superpowers/specs/2026-05-21-chat-server-design.md` — спецификация;
- этот документ;
- (если затрагивается WS) парный `InsurancePlatform/docs/frontend-integration.ru.md`
  и `InsurancePlatform/internal/conn/envelope.go` + `internal/message/message.go`.

Иначе фронтенд и бэкенд разъедутся.
