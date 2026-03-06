import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

from app.core.logger import log

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    log.error("DATABASE_URL environment variable is missing!")
    raise ValueError("Database connection string not found.")

# 🚀 ENTERPRISE CONFIG: 
# pool_pre_ping=True ensures FastAPI checks if Neon is awake before sending a query
# pool_size and max_overflow prevent your server from overloading the DB connections
engine = create_async_engine(
    DATABASE_URL,
    echo=False, # Set to True only if you want to see raw SQL queries in your terminal
    pool_pre_ping=True, 
    pool_size=10,
    max_overflow=20
)

# This is the factory that will generate async database sessions for each user request
AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

async def get_db():
    """
    Dependency to yield an async database session per request.
    Ensures the connection is safely closed after the request finishes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            log.error(f"Database session error: {str(e)}")
            await session.rollback()
            raise
        finally:
            await session.close()