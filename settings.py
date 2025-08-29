import os
from dotenv import load_dotenv
load_dotenv()

ENV = os.getenv("ENV", "prod")  # "prod" | "staging"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
CHANNEL_URL = os.getenv("CHANNEL_URL", default="https://t.me/qa_mind")

# Для статистики/файлов: разные БД под prod/staging
DB_PATH = os.getenv("DB_PATH", f"data/bot_stats_{ENV}.sqlite3")

# (опционально) флаги
MAINTENANCE = os.getenv("MAINTENANCE") == "1"
FEATURE_BETA = os.getenv("FEATURE_BETA") == "1"

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is missing in .env")