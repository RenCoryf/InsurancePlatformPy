class ChatError(Exception):
    """Business-rule error that maps to the Go-facing {code, reason} envelope."""

    def __init__(self, code: str, reason: str, http_status: int = 400):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.http_status = http_status
