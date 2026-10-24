import os
import secrets
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    jwt_secret: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_ttl: int = 3600
    coingecko_url: str = "https://api.coingecko.com/api/v3"
    coingecko_key: str = ""
    coingecko_key_header: str = "x-cg-demo-api-key"
    http_timeout: float = 10.0
    cache_ttl: int = 3600

    def __post_init__(self) -> None:
        if len(self.jwt_secret.encode()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 bytes")
        if self.jwt_ttl <= 0 or self.http_timeout <= 0 or self.cache_ttl <= 0:
            raise ValueError("TTL and timeout must be positive")
        if self.coingecko_key_header not in ("x-cg-demo-api-key", "x-cg-pro-api-key"):
            raise ValueError("Invalid CoinGecko API key header")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jwt_secret=os.getenv("JWT_SECRET") or secrets.token_urlsafe(48),
            jwt_ttl=int(os.getenv("JWT_TTL_SECONDS", "3600")),
            coingecko_url=os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"),
            coingecko_key=os.getenv("COINGECKO_API_KEY", ""),
            coingecko_key_header=os.getenv("COINGECKO_KEY_HEADER", "x-cg-demo-api-key"),
            http_timeout=float(os.getenv("HTTP_TIMEOUT_SECONDS", "10")),
            cache_ttl=int(os.getenv("COINGECKO_CACHE_TTL_SECONDS", "3600")),
        )
