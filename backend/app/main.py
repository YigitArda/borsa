from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.stocks import router as stocks_router
from app.api.backtest import router as backtest_router
from app.api.strategies import router as strategies_router
from app.api.weekly_picks import router as picks_router
from app.api.pipeline import router as pipeline_router
from app.api.research import router as research_router
from app.api.data_quality import router as dq_router
from app.config import settings

app = FastAPI(title="Borsa Research Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key auth — only enforced if API_KEY is set in env
_WRITE_ROUTES = {"/pipeline/", "/strategies/research/", "/weekly-picks/generate", "/backtest/run"}

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    api_key = settings.api_key
    if api_key and request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Check if this is a write route that requires auth
        path = request.url.path
        if any(path.startswith(p) for p in _WRITE_ROUTES):
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token != api_key:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return await call_next(request)

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
