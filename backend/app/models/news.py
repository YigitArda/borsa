from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, Text, Boolean, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    source: Mapped[str | None] = mapped_column(String(100))
    headline: Mapped[str | None] = mapped_column(String(500))
    body_excerpt: Mapped[str | None] = mapped_column(Text)
    ticker_mentions: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float)   # -1 to 1
    sentiment_label: Mapped[str | None] = mapped_column(String(20)) # positive|negative|neutral
    relevance_score: Mapped[float | None] = mapped_column(Float)
    is_earnings: Mapped[bool] = mapped_column(Boolean, default=False)
    is_legal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_product_launch: Mapped[bool] = mapped_column(Boolean, default=False)
    is_analyst_action: Mapped[bool] = mapped_column(Boolean, default=False)
    is_management_change: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[str] = mapped_column(String(50), default="vader_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SocialSentiment(Base):
    __tablename__ = "social_sentiment"
    __table_args__ = (UniqueConstraint("stock_id", "week_ending", "source", name="uq_social_stock_week_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_ending: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    mention_count: Mapped[int | None] = mapped_column(Integer)
    mention_momentum: Mapped[float | None] = mapped_column(Float)
    sentiment_polarity: Mapped[float | None] = mapped_column(Float)
    hype_risk: Mapped[float | None] = mapped_column(Float)
    abnormal_attention: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50), default="yfinance_proxy")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
