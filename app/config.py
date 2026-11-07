import os
from dotenv import load_dotenv
load_dotenv()

class Settings:
    bot_token = os.getenv("BOT_TOKEN", "")
    admin_id = int(os.getenv("ADMIN_ID", "7475644552"))
    database_url = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:////app/data/nethershop.db"
)

settings = Settings()
if not settings.bot_token:
    raise RuntimeError("Укажи BOT_TOKEN в .env")
