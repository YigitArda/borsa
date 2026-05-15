from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth import AuthService
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "viewer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreateRequest(BaseModel):
    scope: str = "read"
    expires_days: int | None = None


class ApiKeyResponse(BaseModel):
    key: str
    scope: str
    expires_at: str | None


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: str


def _get_jwt_secret() -> str:
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT_SECRET must be configured",
        )
    return secret


# ------------------------------------------------------------------
# Dependencies
# ------------------------------------------------------------------
async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> "User":
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    payload = AuthService.verify_access_token(token, _get_jwt_secret())
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    svc = AuthService(db)
    user = await svc.get_user_by_id(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    svc = AuthService(db)
    try:
        user = await svc.create_user(email=req.email, password=req.password, role=req.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"id": user.id, "email": user.email, "role": user.role}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    svc = AuthService(db)
    user = await svc.authenticate(req.email, req.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = AuthService.create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role},
        secret=_get_jwt_secret(),
        expires_delta=None,  # default 30 min
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/api-keys", response_model=ApiKeyResponse)
async def create_api_key(
    req: ApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    svc = AuthService(db)
    raw_key, api_key = await svc.create_api_key(
        user_id=current_user.id,
        scope=req.scope,
        expires_days=req.expires_days,
    )
    return {
        "key": raw_key,
        "scope": api_key.scope or "read",
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
    }


@router.get("/me", response_model=UserResponse)
async def get_me(current_user = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "created_at": str(current_user.created_at),
    }
