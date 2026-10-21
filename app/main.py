from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler, http_exception_handler
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.scoped.errors import ScopeError
from app.services.companion.profile_repository import CompanionProfileError

app = FastAPI(
    title="Aesir AI Service",
    version="0.1.0",
    description="Companion dialogue and tactical service; scoped JSON contract v0.4.",
)


@app.middleware("http")
async def legacy_gate(request: Request, call_next):
    path = request.url.path.rstrip("/")
    discovery = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
    if (not get_settings().scope_legacy_enabled and path not in discovery
            and not path.startswith("/v1/scoped/")):
        error = ScopeError(403, "LEGACY_DISABLED", "Unscoped development endpoints are disabled")
        return JSONResponse(status_code=403, content={"detail": error.as_detail()})
    return await call_next(request)


@app.exception_handler(ScopeError)
async def scope_error_handler(_request: Request, exc: ScopeError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.as_detail()})


@app.exception_handler(RequestValidationError)
async def scoped_validation_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/v1/scoped/"):
        # 不回显带玩家文本/其他归属的数据或存储路径。
        error = ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Invalid v0.4 request structure, identifier or timing")
        return JSONResponse(status_code=422, content={"detail": error.as_detail()})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def scoped_http_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/v1/scoped/"):
        error = ScopeError(exc.status_code, "BUSINESS_REJECTED", "The requested scoped operation is unavailable")
        return JSONResponse(status_code=exc.status_code, content={"detail": error.as_detail()})
    return await http_exception_handler(request, exc)


@app.exception_handler(CompanionProfileError)
async def companion_profile_error_handler(request: Request, exc: CompanionProfileError) -> JSONResponse:
    if request.url.path.startswith("/v1/scoped/"):
        error = ScopeError(503, "STATE_UNAVAILABLE", "Companion profile is unavailable")
        return JSONResponse(status_code=503, content={"detail": error.as_detail()})
    return JSONResponse(status_code=503, content={"detail": "Companion profile is unavailable: " + str(exc)})


app.include_router(router)
