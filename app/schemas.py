from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    WithJsonSchema,
    field_validator,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Credentials(RequestModel):
    username: Annotated[str, Field(min_length=1, max_length=128)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]

    @field_validator("username")
    @classmethod
    def username_valid(cls, value: str) -> str:
        if value != value.strip() or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Username must not contain outer whitespace or control characters")
        return value


class AddCrypto(RequestModel):
    symbol: Annotated[str, Field(min_length=1, max_length=32)]


class ScheduleInput(RequestModel):
    enabled: StrictBool
    interval_seconds: Annotated[StrictInt, Field(ge=10, le=3600)]


Money = Annotated[Decimal, WithJsonSchema({"type": "number"})]


class ErrorResponse(BaseModel):
    error: str


class TokenResponse(BaseModel):
    token: str


class CryptoResponse(BaseModel):
    symbol: str
    name: str
    current_price: Money
    last_updated: datetime


class CryptoEnvelope(BaseModel):
    crypto: CryptoResponse


class CryptoListResponse(BaseModel):
    cryptos: list[CryptoResponse]


class PriceResponse(BaseModel):
    price: Money
    timestamp: datetime


class HistoryResponse(BaseModel):
    symbol: str
    history: list[PriceResponse]


class StatsValues(BaseModel):
    min_price: Money
    max_price: Money
    avg_price: Money
    price_change: Money
    price_change_percent: Money | None
    records_count: int


class StatsResponse(BaseModel):
    symbol: str
    current_price: Money
    stats: StatsValues


class ScheduleResponse(BaseModel):
    enabled: bool
    interval_seconds: int
    last_update: datetime | None
    next_update: datetime | None


class TriggerResponse(BaseModel):
    updated_count: int
    timestamp: datetime


class EmptyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
