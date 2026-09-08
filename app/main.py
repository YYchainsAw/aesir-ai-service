from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.services.companion.profile_repository import CompanionProfileError

app = FastAPI(
    title="Aesir AI Service",
    version="0.1.0",
    description="Local companion dialogue and tactical-command service for Aesir Combat Prototype.",
)


@app.exception_handler(CompanionProfileError)
async def companion_profile_error_handler(_request, exc: CompanionProfileError) -> JSONResponse:
    """人设 YAML 缺失/损坏属于服务端配置故障：统一返回 503 而非裸 500，
    让 UE 侧能区分「配置问题」与「未知异常」。"""
    return JSONResponse(
        status_code=503,
        content={"detail": "Companion profile is unavailable: " + str(exc)},
    )


app.include_router(router)
