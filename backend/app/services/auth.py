from datetime import datetime, timedelta
from typing import Any
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, ApiKey


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Password hashing (bcrypt)
    # ------------------------------------------------------------------
    @staticmethod
    def _get_bcrypt():
        try:
            import bcrypt
        except ImportError as exc:
            raise RuntimeError("bcrypt is required for password hashing. Install it with: pip install bcrypt") from exc
        return bcrypt

    @classmethod
    def hash_password(cls, password: str) -> str:
        bcrypt = cls._get_bcrypt()
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    @classmethod
    def verify_password(cls, password: str, hashed: str) -> bool:
        bcrypt = cls._get_bcrypt()
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------
    @staticmethod
    def _get_jwt():
        try:
            import jwt
        except ImportError as exc:
            raise RuntimeError("PyJWT is required. Install it with: pip install PyJWT") from exc
        return jwt

    @classmethod
    def create_access_token(cls, data: dict, secret: str, expires_delta: timedelta | None = None) -> str:
        jwt = cls._get_jwt()
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=30))
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, secret, algorithm="HS256")

    @classmethod
    def verify_access_token(cls, token: str, secret: str) -> dict[str, Any] | None:
        jwt = cls._get_jwt()
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload
        except Exception:
            return None

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------
    async def create_user(self, email: str, password: str, role: str = "viewer") -> User:
        existing = await self.db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise ValueError("User with this email already exists")

        user = User(
            email=email,
            hashed_password=self.hash_password(password),
            role=role,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if not self.verify_password(password, user.hashed_password):
            return None
        return user

    async def get_user_by_id(self, user_id: int) -> User | None:
        return await self.db.get(User, user_id)

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------
    async def create_api_key(self, user_id: int, scope: str | None = None, expires_days: int | None = None) -> tuple[str, ApiKey]:
        """Return the plain API key and the persisted ApiKey row."""
        raw_key = "borsa_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = ApiKey(
            key_hash=key_hash,
            user_id=user_id,
            scope=scope or "read",
            expires_at=(datetime.utcnow() + timedelta(days=expires_days)) if expires_days else None,
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)
        return raw_key, api_key

    async def verify_api_key(self, raw_key: str) -> ApiKey | None:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        result = await self.db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None
        if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
            return None
        return api_key
