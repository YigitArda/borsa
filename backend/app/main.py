from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.stocks import router as stocks_router
from app.api.backtest import router as backtest_router
from app.api.strategies import router as strategies_router
from app.api.weekly_picks import router as picks_router
from app.api.pipeline import router as pipeline_router

app = FastAPI(title="Borsa Research Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks_router)
app.include_router(backtest_router)
app.include_router(strategies_router)
app.include_router(picks_router)
app.include_router(pipeline_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Borsa Research Engine — not financial advice"}
