from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api.main_router import api_router
from app.api.routers.internal import router as internal_router
from app.core.config import settings
from app.core.minio_client import build_minio_client, ensure_bucket
from app.services.errors import ChatError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    app.state.minio = build_minio_client()
    try:
        ensure_bucket(app.state.minio, settings.minio_bucket)
    except Exception:
        # MinIO may be unreachable in test/dev environments; tests inject a fake client.
        pass
    yield
    await app.state.redis.close()


app = FastAPI(
    title="Insurance Platform API",
    description="API for Insurance Platform",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(api_router)
app.include_router(internal_router)  # mounted at /internal/*, no /api/v1 prefix


@app.exception_handler(RequestValidationError)
async def _internal_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """For /internal/* routes, convert FastAPI's 422 into Go's expected
    {code: 'validation', reason: '<first error>'} envelope. Other routes get
    the default FastAPI 422."""
    if request.url.path.startswith("/internal/"):
        errs = exc.errors()
        first = errs[0] if errs else {"msg": "invalid request"}
        reason = first.get("msg", "invalid request")
        return JSONResponse(status_code=400, content={"code": "validation", "reason": reason})
    # default-shape fallback for non-internal routes (keep FastAPI behavior)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(ChatError)
async def _chat_error_handler(request: Request, exc: ChatError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"code": exc.code, "reason": exc.reason})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
