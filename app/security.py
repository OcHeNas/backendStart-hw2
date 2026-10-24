import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt

from app.domain import Unauthorized, User, UserRepository, utcnow


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=5)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=5)
    return hmac.compare_digest(actual, bytes.fromhex(expected))


class AuthService:
    def __init__(self, users: UserRepository, secret: str, ttl: int = 3600) -> None:
        self.users = users
        self.secret = secret
        self.ttl = ttl
        self._dummy = hash_password(secrets.token_urlsafe(32))

    def _token(self, user: User) -> str:
        now = utcnow()
        return jwt.encode(
            {
                "sub": user.username,
                "uid": user.user_id,
                "iat": now,
                "exp": now + timedelta(seconds=self.ttl),
                "iss": "cryptoserver",
                "aud": "cryptoserver",
            },
            self.secret,
            algorithm="HS256",
        )

    def register(self, username: str, password: str) -> str:
        user = self.users.add(username, hash_password(password))
        return self._token(user)

    def login(self, username: str, password: str) -> str:
        user = self.users.get(username)
        valid = verify_password(password, user.password_hash if user else self._dummy)
        if user is None or not valid:
            raise Unauthorized("Invalid username or password")
        return self._token(user)

    def authenticate(self, token: str) -> str:
        try:
            data = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                issuer="cryptoserver",
                audience="cryptoserver",
                options={"require": ["sub", "uid", "exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized("Invalid or expired token") from exc
        username = data["sub"]
        user = self.users.get(username) if isinstance(username, str) else None
        if user is None or data["uid"] != user.user_id:
            raise Unauthorized("Invalid or expired token")
        return username
