import base64
import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def admin_basic_auth(authorization: str = Header(default="")) -> None:
    if not authorization.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="basic auth required",
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
        )
    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
        login, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed credentials")

    login_ok = secrets.compare_digest(login, settings.admin_login)
    password_ok = secrets.compare_digest(password, settings.admin_password)
    if not (login_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
        )
