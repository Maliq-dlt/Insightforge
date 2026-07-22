from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from insightforge.config import Settings
from insightforge.storage.database import TraceStore


class AuthenticationError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


_PERMISSIONS = {
    "viewer": {"read"},
    "analyst": {"read", "analyze", "execute_python"},
    "admin": {"read", "analyze", "execute_python", "admin"},
}


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    username: str
    role: str


class AuthService:
    def __init__(self, settings: Settings, store: TraceStore) -> None:
        self.settings = settings
        self.store = store
        self.enabled = settings.auth_enabled
        if self.enabled:
            self._bootstrap()

    def _bootstrap(self) -> None:
        username = self.settings.auth_bootstrap_username
        password = self.settings.auth_bootstrap_password
        if not username or not password:
            raise ValueError(
                "AUTH_BOOTSTRAP_USERNAME dan AUTH_BOOTSTRAP_PASSWORD wajib saat AUTH_ENABLED=true."
            )
        if self.store.get_user_by_username(username) is None:
            self.create_user(username, password, "admin")

    def create_user(self, username: str, password: str, role: str) -> dict[str, Any]:
        if len(username.strip()) < 3:
            raise ValueError("Username minimal tiga karakter.")
        if len(password) < 12:
            raise ValueError("Password minimal 12 karakter.")
        if self.store.get_user_by_username(username.strip()) is not None:
            raise ValueError("Username sudah digunakan.")
        user = self.store.create_user(username.strip(), self._hash_password(password), role)
        return self.public_user(user)

    def login(self, username: str, password: str) -> dict[str, Any]:
        if not self.enabled:
            raise AuthenticationError("Authentication tidak aktif.")
        user = self.store.get_user_by_username(username)
        if user is None or not user.get("active") or not self._verify_password(password, user["password_hash"]):
            raise AuthenticationError("Username atau password salah.")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=self.settings.auth_token_ttl_hours)
        self.store.create_token(self._token_hash(token), user["id"], expires_at.isoformat())
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
            "user": self.public_user(user),
        }

    def resolve(self, token: str | None) -> AuthContext:
        if not self.enabled:
            return AuthContext("system", "system", "admin")
        if not token:
            raise AuthenticationError("Bearer token wajib.")
        user = self.store.get_user_by_token(self._token_hash(token))
        if user is None:
            raise AuthenticationError("Token invalid atau expired.")
        return AuthContext(user["id"], user["username"], user["role"])

    def require(self, context: AuthContext, permission: str) -> None:
        if permission not in _PERMISSIONS.get(context.role, set()):
            raise AuthorizationError(f"Role {context.role} tidak memiliki izin {permission}.")

    def revoke(self, token: str) -> None:
        self.store.revoke_token(self._token_hash(token))

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in user.items() if key != "password_hash"}

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt, expected = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=base64.urlsafe_b64decode(salt),
                n=int(n),
                r=int(r),
                p=int(p),
            )
            return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
