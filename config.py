import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", 0))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    MONGO_URI = os.getenv("MONGO_URI", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "pdf_converter")
    OWNER_ID = int(os.getenv("OWNER_ID", 0))

    # AI
    ENABLE_AI = os.getenv("ENABLE_AI", "false").lower() == "true"
    AI_API_KEY = os.getenv("AI_API_KEY", "")
    AI_API_URL = os.getenv("AI_API_URL", "https://agentrouter.org/api/v1/chat/completions")
    AI_MODEL = os.getenv("AI_MODEL", "glm-5.2")
