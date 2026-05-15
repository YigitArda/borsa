from datetime import datetime
from sqlalchemy import String, DateTime, Text, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ArxivPaper(Base):
    __tablename__ = "arxiv_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    arxiv_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    authors: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[datetime | None] = mapped_column(DateTime)
    categories: Mapped[str | None] = mapped_column(String(200))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResearchInsight(Base):
    __tablename__ = "research_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int | None] = mapped_column(Integer)
    arxiv_id: Mapped[str | None] = mapped_column(String(50), index=True)
    feature_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    pseudocode: Mapped[str | None] = mapped_column(Text)
    applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="new")  # new | approved | implemented | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
