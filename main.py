import os
import sys
import subprocess
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Создаём папку для базы
DB_DIR = Path("/app/data")
DB_DIR.mkdir(parents=True, exist_ok=True)

# Единый путь для бота и Alembic
os.environ["DATABASE_URL"] = (
    "sqlite+aiosqlite:////app/data/nethershop.db"
)

# Устанавливаем зависимости
subprocess.check_call([
    sys.executable, "-m", "pip",
    "install", "-r", str(ROOT / "requirements.txt")
])

# Миграции применяет сам бот при старте (app/__main__.py).

# Запускаем бота
sys.path.insert(0, str(ROOT))
runpy.run_module("app", run_name="__main__")