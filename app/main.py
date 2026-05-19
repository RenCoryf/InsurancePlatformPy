from contextlib import asynccontextmanager

import dotenv
import redis.asyncio as redis
from fastapi import FastAPI

from app.api.main_router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    dotenv.load_dotenv()
    app.state.redis = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    yield
    await app.state.redis.close()


app = FastAPI(
    title="Insurance Platform API",
    description="API for Insurance Platform",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
