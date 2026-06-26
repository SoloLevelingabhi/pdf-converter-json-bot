# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot Configuration
    API_ID = int(os.getenv("API_ID", 0))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    
    # MongoDB Configuration
    MONGO_URI = os.getenv("MONGO_URI", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "pdf_converter")
    
    # Bot Settings
    OWNER_ID = int(os.getenv("OWNER_ID", 0))
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    SUPPORTED_FORMATS = [".pdf"]
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "bot.log")
    
    # Performance
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 10))
    MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", 5))
    
    # Gemini API Configuration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Feature Flags
    ENABLE_OCR = os.getenv("ENABLE_OCR", "false").lower() == "true"
    ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true"
    ENABLE_ANALYTICS = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"
