from fastapi import FastAPI

from app.api.main_router import api_router

app = FastAPI(
    title="Insurance Platform API",
    description="API for Insurance Platform",
    version="0.1.0",
)

app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
