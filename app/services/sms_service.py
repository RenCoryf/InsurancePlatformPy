import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SMSCResult:
    id: Optional[int] = None


class SMSCError(Exception):
    def __init__(self, code: int, message: str, sms_id: int | None = None):
        self.code = code
        self.message = message
        self.sms_id = sms_id
        super().__init__(f"[{code}] {message}")


class SMSService_SMSC:
    URL = "https://smsc.ru"
    ReserveURL = "https://www2.smsc.ru."

    def __init__(
        self,
        username: str,
        password: str,
        lk_url: str,
    ):
        self.username = username
        self.password = password
        self._lk_url = lk_url

    @classmethod
    def with_credentials(
        cls, username: str, password: str, lk_url: str
    ) -> "SMSService_SMSC":
        return cls(username=username, password=password, lk_url=lk_url)

    def _gen_mes(self, code: str) -> str:
        return f"Ваш код подтверждения: {code}\nЛичный кабинет: {self.ReserveURL}"

    def _parse_smsc_response(self, data: dict) -> SMSCResult:
        if "error" not in data:
            return SMSCResult(id=data.get("id"))

        raise SMSCError(
            code=data["error_code"],
            message=data["error"],
            sms_id=data.get("id"),
        )

    async def send_sms(self, phone: str, code: str) -> SMSCResult:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.URL}/sys/send.php",
                params={
                    "login": self.username,
                    "psw": self.password,
                    "phones": phone,
                    "mes": self._gen_mes(code),
                },
            )
        data = resp.json()
        return self._parse_smsc_response(data)
