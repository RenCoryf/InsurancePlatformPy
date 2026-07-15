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
        sender: str | None = None,
    ):
        self.username = username
        self.password = password
        self._lk_url = lk_url
        self.sender = sender or None

    @classmethod
    def with_credentials(
        cls, username: str, password: str, lk_url: str, sender: str | None = None
    ) -> "SMSService_SMSC":
        return cls(username=username, password=password, lk_url=lk_url, sender=sender)

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

    async def send_message(self, phone: str, message: str) -> SMSCResult:
        params = {
            "login": self.username,
            "psw": self.password,
            "phones": phone,
            "mes": message,
            "fmt": 3,  # JSON-ответ
        }
        if self.sender:
            params["sender"] = self.sender
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.URL}/sys/send.php", params=params)
        data = resp.json()
        return self._parse_smsc_response(data)

    async def send_sms(self, phone: str, code: str) -> SMSCResult:
        return await self.send_message(phone, self._gen_mes(code))
