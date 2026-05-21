import json
import secrets

from redis import Redis


class AttemptsError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


# TODO BETA rate limiting via redis
class CodeManager:
    def __init__(self, redis_client: Redis):
        self._redis_client = redis_client

    def _generate_code(self) -> int:
        return secrets.randbelow(1_000_000)

    async def _save_code(self, phone: str, code: str) -> None:
        key = f"otp:{phone}"
        data = {
            "code": code,
            "attempts": 0,
        }
        await self._redis_client.set(
            key,
            json.dumps(data),
            ex=300,
        )

    async def get_code(self, phone: str) -> int:
        code = self._generate_code()
        await self._save_code(phone, str(code))
        return code

    async def verify_code(self, phone: str, code: str) -> bool:
        key = f"otp:{phone}"

        raw = await self._redis_client.get(key)
        if not raw:
            return False

        data = json.loads(raw)

        if data["code"] != code:
            data["attempts"] += 1

            if data["attempts"] >= 5:
                await self._redis_client.delete(key)
                raise AttemptsError("Attempts limit exceeded")

            await self._redis_client.set(key, json.dumps(data), ex=300)
            return False

        await self._redis_client.delete(key)
        return True

    async def _delete_code(self, phone: str) -> None:
        key = f"otp:{phone}"
        await self._redis_client.delete(key)

    async def new_code(self, phone: str) -> int:
        await self._delete_code(phone)
        code = await self.get_code(phone)
        return code
