import asyncio
from app.db.database import engine, Base
# We MUST import models here so SQLAlchemy registers them before creating tables
from app.db import models 
from app.core.logger import log

async def create_tables():
    log.info("🔌 Connecting to Neon Database...")
    try:
        async with engine.begin() as conn:
            log.info("🏗️ Pushing schema to PostgreSQL...")
            # This translates your Python classes into raw SQL CREATE TABLE commands
            await conn.run_sync(Base.metadata.create_all)
        log.info("✅ Database tables created successfully!")
    except Exception as e:
        log.error(f"❌ Failed to create tables: {str(e)}")
    finally:
        # Gracefully close the connection pool
        await engine.dispose()

if __name__ == "__main__":
    # Run the async function
    asyncio.run(create_tables())