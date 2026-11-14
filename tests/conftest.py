import os
import tempfile

# Переменные окружения нужны до импорта app.* (config читает их при импорте).
_tmp = tempfile.mkdtemp(prefix="nethershop-test-")
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"

import pytest_asyncio  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app import models  # noqa: E402,F401


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
