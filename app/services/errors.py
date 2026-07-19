class ChatError(Exception):
    """Business-rule error that maps to the Go-facing {code, reason} envelope."""

    def __init__(self, code: str, reason: str, http_status: int = 400):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.http_status = http_status


class ReferralLinkInvalidError(Exception):
    """Реферальный код не найден, либо реферер заблокирован/удалён.

    Обработчик в app.main отдаёт 422 {"error": "Реферальная ссылка недействительна"}.
    """

    MESSAGE = "Реферальная ссылка недействительна"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)
        self.message = message or self.MESSAGE


class UserBlockedError(Exception):
    """Попытка входа/действия заблокированным пользователем — 403."""

    def __init__(self, reason: str | None = None, comment: str | None = None):
        self.reason = reason
        self.comment = comment
        super().__init__("Аккаунт заблокирован")


class SmsRateLimitError(Exception):
    """Превышен дневной лимит SMS на номер — 429."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Превышен лимит SMS: не более {limit} в сутки")
