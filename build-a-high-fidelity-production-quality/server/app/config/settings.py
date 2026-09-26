import os
from pathlib import Path
from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parents[2]
load_dotenv(SERVER_DIR / ".env")

class Settings:
    port = int(os.getenv("PORT", "5000"))
    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "pharmsync")
    db_port = int(os.getenv("DB_PORT", "3306"))
    jwt_secret = os.getenv("JWT_SECRET", "")
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    ai_provider = os.getenv("AI_PROVIDER", "none").strip().lower()
    huggingface_api_key = os.getenv("HUGGINGFACE_API_KEY", "")
    huggingface_model = os.getenv("HUGGINGFACE_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    ocr_space_api_key = os.getenv("OCR_SPACE_API_KEY", "")
    client_origin = os.getenv("CLIENT_ORIGIN", "http://localhost:5173")
    client_origins = [origin.strip() for origin in os.getenv("CLIENT_ORIGINS", client_origin).split(",") if origin.strip()]
    restock_days_threshold = float(os.getenv("RESTOCK_DAYS_THRESHOLD", "15"))
    inventory_agent_hour = int(os.getenv("INVENTORY_AGENT_HOUR", "2"))
    inventory_agent_minute = int(os.getenv("INVENTORY_AGENT_MINUTE", "0"))
    max_user_order_quantity = int(os.getenv("MAX_USER_ORDER_QUANTITY", "2"))
    velocity_fast_units_per_day = float(os.getenv("VELOCITY_FAST_UNITS_PER_DAY", "1.0"))
    velocity_slow_units_per_day = float(os.getenv("VELOCITY_SLOW_UNITS_PER_DAY", "0.1"))

settings = Settings()
