import json
import secrets

from redis.asyncio import Redis


class AttemptsError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class CodeManager:
    """Хранит одноразовые SMS-коды в Redis (TTL 5 минут, до 5 попыток ввода)."""

    CODE_TTL_SECONDS = 300
    MAX_ATTEMPTS = 5

    def __init__(self, redis_client: Redis):
        self._redis_client = redis_client

    def _generate_code(self) -> str:
        # Всегда 6 цифр: DTO требует ровно 6 символов.
        return f"{secrets.randbelow(1_000_000):06d}"

    async def _save_code(self, phone: str, code: str) -> None:
        key = f"otp:{phone}"
        data = {
            "code": code,
            "attempts": 0,
        }
        await self._redis_client.set(
            key,
            json.dumps(data),
            ex=self.CODE_TTL_SECONDS,
        )

    async def get_code(self, phone: str) -> str:
        code = self._generate_code()
        await self._save_code(phone, code)
        return code

    async def verify_code(self, phone: str, code: str) -> bool:
        key = f"otp:{phone}"

        raw = await self._redis_client.get(key)
        if not raw:
            return False

        data = json.loads(raw)

        if data["code"] != code:
            data["attempts"] += 1

            if data["attempts"] >= self.MAX_ATTEMPTS:
                await self._redis_client.delete(key)
                raise AttemptsError("Attempts limit exceeded")

            await self._redis_client.set(key, json.dumps(data), ex=self.CODE_TTL_SECONDS)
            return False

        await self._redis_client.delete(key)
        return True

    async def _delete_code(self, phone: str) -> None:
        key = f"otp:{phone}"
        await self._redis_client.delete(key)

    async def new_code(self, phone: str) -> str:
        await self._delete_code(phone)
        code = await self.get_code(phone)
        return code
