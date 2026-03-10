"""Configuration settings for CogniFlow."""
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings
from pydantic import Field

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """CogniFlow application settings."""
    
    # Application
    app_name: str = "CogniFlow"
    debug: bool = False
    log_level: str = "INFO"
    
    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/cogniflow"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Market Data (FMP)
    fmp_api_key: str = Field(default="", description="Financial Modeling Prep API key")
    
    # LLM (Optional)
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    
    # Perception Module
    perception_monitoring_interval: int = 60  # seconds
    price_anomaly_threshold: float = 2.5  # Z-Score threshold
    volume_spike_threshold: float = 2.0   # Volume multiplier
    volatility_change_threshold: float = 0.5  # 50% change
    
    # Intent Prediction
    intent_min_confidence: float = 0.6
    intent_min_overall_score: float = 0.5
    intent_expiration_hours: int = 24
    intent_max_candidates: int = 3
    
    # Context Management
    working_memory_budget: int = 4000      # tokens
    short_term_memory_budget: int = 16000  # tokens
    long_term_memory_budget: int = 64000   # tokens
    
    model_config = {
        "env_file": PROJECT_ROOT / ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Global settings instance
settings = Settings()
