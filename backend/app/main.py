import json
import hashlib
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.api.stocks import router as stocks_router
from app.api.backtest import router as backtest_router
from app.api.strategies import router as strategies_router
from app.api.weekly_picks import router as picks_router
from app.api.pipeline import router as pipeline_router
from app.api.research import router as research_router
from app.api.data_quality import router as dq_router
from app.api.verification import router as verification_router
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.selected_stocks import router as selected_stocks_router
from app.api.export import router as export_router
from app.api.scientific import router as scientific_router
from app.config import settings
from app.middleware.logging import LoggingMiddleware
from app.logging_config import configure_logging
from app.websocket import websocket_endpoint

limiter = Limiter(key_func=get_remote_address)

# Configure structured logging on startup
configure_logging(log_level="INFO", json=True)

app = FastAPI(title="Borsa Research Engine", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(LoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key auth — only enforced if API_KEY is set in env
_WRITE_ROUTES = {
    "/pipeline/",
    "/strategies/research/",
    "/strategies/",
    "/weekly-picks/generate",
    "/weekly-picks/paper/",
    "/backtest/",
    "/research/optimize",
    "/scientific/",
    "/api/v1/weekly-pipeline",
}

# Heavy read endpoints cached in Redis (TTL 5 minutes)
_CACHED_ROUTES = {
    "/weekly-picks",
    "/research/promotions",
    "/research/risk-warnings",
    "/data-quality",
}

# Per-endpoint rate limits (requests per minute)
_RATE_LIMITS = {
    # Heavy endpoints
    "/backtest/run": 5,
    "/backtest/direct": 5,
    "/backtest/cpcv": 5,
    "/backtest/portfolio": 5,
    "/strategies/research/start": 5,
    "/research/ablation": 5,
    "/research/optimize": 5,
    "/scientific/": 10,
    "/api/v1/weekly-pipeline": 5,
    # Write endpoints
    "/pipeline/": 30,
    "/strategies/": 30,
    "/weekly-picks/generate": 30,
    "/weekly-picks/paper/": 30,
    "/auth/": 30,
    # Export endpoints
    "/export/": 10,
    # Read endpoints (default)
    "__default__": 100,
}

# Simple in-memory rate limit store: {client_ip: {endpoint: [timestamps]}}
_rate_limit_store: dict = {}


def _check_rate_limit(client_ip: str, path: str) -> tuple[bool, int, int]:
    """Check if request is within rate limit. Returns (allowed, limit, remaining)."""
    import time
    now = time.time()
    window = 60  # 1 minute

    # Find applicable limit
    limit = _RATE_LIMITS.get("__default__")
    for prefix, l in _RATE_LIMITS.items():
        if prefix != "__default__" and path.startswith(prefix):
            limit = l
            break

    # Clean old entries
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = {}
    if path not in _rate_limit_store[client_ip]:
        _rate_limit_store[client_ip][path] = []

    # Remove timestamps older than window
    _rate_limit_store[client_ip][path] = [
        ts for ts in _rate_limit_store[client_ip][path] if now - ts < window
    ]

    requests_in_window = len(_rate_limit_store[client_ip][path])
    remaining = max(0, limit - requests_in_window - 1)

    if requests_in_window >= limit:
        return False, limit, 0

    _rate_limit_store[client_ip][path].append(now)
    return True, limit, remaining


_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis as redis_lib
            _redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply per-endpoint rate limiting."""
    if request.method == "OPTIONS":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    allowed, limit, remaining = _check_rate_limit(client_ip, path)
    if not allowed:
        response = JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"Rate limit exceeded: {limit} requests per minute for this endpoint"},
        )
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = "0"
        response.headers["Retry-After"] = "60"
        return response

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    api_key = settings.api_key
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        path = request.url.path
        if any(path.startswith(p) for p in _WRITE_ROUTES):
            if not api_key:
                if settings.environment.lower() in {"prod", "production", "staging"}:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="API_KEY must be set for write routes outside development",
                    )
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token != api_key:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return await call_next(request)


@app.middleware("http")
async def redis_cache_middleware(request: Request, call_next):
    if request.method != "GET":
        return await call_next(request)

    path = request.url.path
    if not any(path.startswith(r) for r in _CACHED_ROUTES):
        return await call_next(request)

    r = _get_redis()
    if r is None:
        return await call_next(request)

    cache_key = "cache:" + hashlib.md5(str(request.url).encode()).hexdigest()
    try:
        cached = r.get(cache_key)
        if cached:
            return JSONResponse(content=json.loads(cached))
    except Exception:
        pass

    response = await call_next(request)

    if response.status_code == 200:
        try:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            r.setex(cache_key, 300, body.decode())
            return JSONResponse(content=json.loads(body))
        except Exception:
            pass

    return response


app.include_router(stocks_router)
app.include_router(backtest_router)
app.include_router(strategies_router)
app.include_router(picks_router)
app.include_router(pipeline_router)
app.include_router(research_router)
app.include_router(dq_router)
app.include_router(verification_router)
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(selected_stocks_router)
app.include_router(export_router)
app.include_router(scientific_router)

app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Borsa Research Engine — not financial advice"}
