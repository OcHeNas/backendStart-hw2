import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import simplejson
from fastapi import APIRouter, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app import schemas
from app.coingecko import CoinGecko
from app.config import Settings
from app.domain import (
    Conflict,
    Crypto,
    InvalidInput,
    NotFound,
    PriceProvider,
    ProviderError,
    ServiceError,
    Unauthorized,
)
from app.memory import MemoryCryptos, MemoryUsers
from app.scheduler import Scheduler
from app.schemas import AddCrypto, Credentials, ScheduleInput
from app.security import AuthService
from app.services import CryptoService

logger = logging.getLogger(__name__)


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"Cannot serialize {type(value)}")


class ExactJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return simplejson.dumps(
            content, use_decimal=True, allow_nan=False, default=json_default, ensure_ascii=False
        ).encode("utf-8")


def crypto_json(crypto: Crypto) -> dict[str, Any]:
    return {
        "symbol": crypto.coin.symbol,
        "name": crypto.coin.name,
        "current_price": crypto.latest.price,
        "last_updated": crypto.latest.timestamp,
    }


def create_app(
    settings: Settings | None = None,
    provider: PriceProvider | None = None,
    *,
    start_scheduler: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    provider = provider or CoinGecko(settings)
    repository = MemoryCryptos()
    users = MemoryUsers()
    service = CryptoService(repository, provider)
    auth = AuthService(users, settings.jwt_secret, settings.jwt_ttl)
    scheduler = Scheduler(service)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_scheduler:
            scheduler.start()
        try:
            yield
        finally:
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(scheduler.stop)
            provider.close()

    app = FastAPI(
        title="Cryptocurrency price server",
        version="1.0.0",
        lifespan=lifespan,
        responses={
            400: {"model": schemas.ErrorResponse},
            401: {"model": schemas.ErrorResponse},
            404: {"model": schemas.ErrorResponse},
            409: {"model": schemas.ErrorResponse},
            500: {"model": schemas.ErrorResponse},
        },
    )
    app.state.service = service
    app.state.auth = auth
    app.state.scheduler = scheduler

    @app.exception_handler(ServiceError)
    async def application_error(_request, exc: ServiceError):
        statuses = {
            InvalidInput: 400,
            Unauthorized: 401,
            NotFound: 404,
            Conflict: 409,
            ProviderError: 500,
        }
        status = statuses.get(type(exc), 500)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return ExactJSONResponse({"error": str(exc)}, status_code=status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        return ExactJSONResponse({"error": "Invalid request body or parameters"}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc: HTTPException):
        return ExactJSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(_request, _exc):
        logger.exception("Unhandled request failure")
        return ExactJSONResponse({"error": "Internal server error"}, status_code=500)

    bearer = HTTPBearer(auto_error=False)

    def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        if credentials is None:
            raise Unauthorized("Bearer token required")
        return auth.authenticate(credentials.credentials)

    @app.post(
        "/auth/register", status_code=201, tags=["auth"], response_model=schemas.TokenResponse
    )
    def register(body: Credentials):
        return ExactJSONResponse(
            {"token": auth.register(body.username, body.password)}, status_code=201
        )

    @app.post("/auth/login", tags=["auth"], response_model=schemas.TokenResponse)
    def login(body: Credentials):
        return ExactJSONResponse({"token": auth.login(body.username, body.password)})

    protected = APIRouter(dependencies=[Depends(current_user)])

    @protected.get("/crypto", tags=["crypto"], response_model=schemas.CryptoListResponse)
    def list_cryptos():
        return ExactJSONResponse({"cryptos": [crypto_json(c) for c in repository.all()]})

    @protected.post(
        "/crypto", status_code=201, tags=["crypto"], response_model=schemas.CryptoEnvelope
    )
    def add_crypto(body: AddCrypto):
        return ExactJSONResponse({"crypto": crypto_json(service.add(body.symbol))}, status_code=201)

    @protected.get("/crypto/{symbol}", tags=["crypto"], response_model=schemas.CryptoResponse)
    def get_crypto(symbol: str):
        return ExactJSONResponse(crypto_json(service.get(symbol)))

    @protected.put(
        "/crypto/{symbol}/refresh", tags=["crypto"], response_model=schemas.CryptoEnvelope
    )
    def refresh(symbol: str):
        return ExactJSONResponse({"crypto": crypto_json(service.refresh(symbol))})

    @protected.get(
        "/crypto/{symbol}/history", tags=["crypto"], response_model=schemas.HistoryResponse
    )
    def history(symbol: str):
        crypto = service.get(symbol)
        return ExactJSONResponse(
            {
                "symbol": crypto.coin.symbol,
                "history": [{"price": p.price, "timestamp": p.timestamp} for p in crypto.history],
            }
        )

    @protected.get("/crypto/{symbol}/stats", tags=["crypto"], response_model=schemas.StatsResponse)
    def stats(symbol: str):
        crypto = service.get(symbol)
        return ExactJSONResponse(
            {
                "symbol": crypto.coin.symbol,
                "current_price": crypto.latest.price,
                "stats": crypto.stats(),
            }
        )

    @protected.delete("/crypto/{symbol}", tags=["crypto"], response_model=schemas.EmptyResponse)
    def delete(symbol: str):
        service.delete(symbol)
        return ExactJSONResponse({})

    @protected.get("/schedule", tags=["schedule"], response_model=schemas.ScheduleResponse)
    def get_schedule():
        return ExactJSONResponse(scheduler.settings())

    @protected.put("/schedule", tags=["schedule"], response_model=schemas.ScheduleInput)
    def put_schedule(body: ScheduleInput):
        return ExactJSONResponse(scheduler.configure(body.enabled, body.interval_seconds))

    @protected.post("/schedule/trigger", tags=["schedule"], response_model=schemas.TriggerResponse)
    def trigger():
        return ExactJSONResponse(scheduler.trigger())

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    app.include_router(protected)
    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                if isinstance(operation, dict):
                    operation.get("responses", {}).pop("422", None)
        return schema

    app.openapi = openapi
    return app
