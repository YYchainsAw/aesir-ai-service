from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="Aesir AI Service",
    version="0.1.0",
    description="Local command-parsing service for Aesir Combat Prototype.",
)
app.include_router(router)




