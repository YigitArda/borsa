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
from app.config import settings

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Borsa Research Engine", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key auth — only enforced if API_KEY is set in env
_WRITE_ROUTES = {"/pipeline/", "/strategies/research/", "/strategies/", "/weekly-picks/generate", "/weekly-picks/paper/", "/backtest/"}

# Heavy read endpoints cached in Redis (TTL 5 minutes)
_CACHED_ROUTES = {
    "/weekly-picks",
    "/research/promotions",
    "/research/risk-warnings",
    "/data-quality",
}

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Borsa Research Engine — not financial advice"}
