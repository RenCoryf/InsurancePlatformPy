from fastapi import Request


async def get_redis(request: Request):
    """Async-клиент Redis из lifespan-состояния приложения.

    Возвращает None, если lifespan не выполнялся (например, в тестах через
    ASGITransport) — зависимые сервисы обязаны переживать отсутствие Redis.
    """
    return getattr(request.app.state, "redis", None)
