from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = None
AsyncSessionLocal = None


class Base(DeclarativeBase):
    pass


def get_engine():
    global engine
    if engine is None:
        engine = create_async_engine(settings.database_url, echo=False)
    return engine


def get_sessionmaker():
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        AsyncSessionLocal = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return AsyncSessionLocal


async def get_db():
    async_session = get_sessionmaker()
    async with async_session() as session:
        yield session
