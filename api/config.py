"""ThoughtSpot → Power BI Migration API — Configuration"""
from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class APIConfig(BaseSettings):
    """Configuration for the ThoughtSpot→PBI Migration FastAPI application"""

    # API Settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"
    API_TITLE: str = "ThoughtSpot to Power BI Migration API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "Convert ThoughtSpot TML exports to Power BI PBIP projects with DAX formulas"

    # File Upload Settings
    UPLOAD_DIR: str = "./uploads"
    EXPORT_DIR: str = "./exports"

    # Database Settings
    DATABASE_PATH: str = "../migrations.db"

    # CORS Settings
    # Set CORS_ORIGINS env var as comma-separated list for production, e.g.:
    #   CORS_ORIGINS=https://my-frontend.azurewebsites.net,https://my-cdn.azureedge.net
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "*",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # Logging
    LOG_LEVEL: str = "INFO"

    # LLM Settings (Azure OpenAI / Gemini compatibility)
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_DEPLOYMENT_NAME: Optional[str] = "gemini-3.1-flash-lite-preview"
    ENABLE_LLM_VALIDATION: bool = True
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4000
    LLM_SLEEP_TIME: float = 0.0


    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"

    def ensure_directories(self):
        """Ensure all required directories exist"""
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.EXPORT_DIR, exist_ok=True)
        db_dir = os.path.dirname(self.DATABASE_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)


# Global config instance
config = APIConfig()
