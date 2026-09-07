from fastapi import FastAPI

from app.api.routes import router
from app.api.v1.companion import router as companion_router
from app.api.v1.speech import router as speech_router
from app.api.v1.voice import router as voice_router

app = FastAPI(
    title="Aesir AI Service",
    version="0.1.0",
    description="Local companion dialogue and tactical-command service for Aesir Combat Prototype.",
)
app.include_router(router)
app.include_router(companion_router)
app.include_router(voice_router)
app.include_router(speech_router)
