import json
import os
from functools import lru_cache
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from typing import Optional, List
from datetime import timedelta


class Settings(BaseSettings):
    """Configuration for ROSE Clinical Triage Engine - Open Source Edition with Context Caching"""
    
    # Server config
    ENVIRONMENT: str = Field("production", env="ENVIRONMENT")
    CORS_ORIGINS: str = Field("", env="CORS_ORIGINS")
    PORT: int = Field(7860, env="PORT")
    
    # Prompt management
    PROMPTS_DIR: str = Field("app/prompts", env="PROMPTS_DIR")
    
    # Gemini config (ONLY cloud dependency remaining)
    GEMINI_API_KEY: str = Field(..., env="GEMINI_API_KEY")
    GEMINI_MODEL: str = Field("gemini-2.5-flash-lite", env="GEMINI_MODEL")
    GEMINI_TEMPERATURE: float = Field(0.3, ge=0.0, le=1.0)
    
    # 🔹 NEW: Context Caching Configuration
    GEMINI_CACHE_ENABLED: bool = Field(True, env="GEMINI_CACHE_ENABLED")
    GEMINI_CACHE_TTL_MINUTES: int = Field(60, env="GEMINI_CACHE_TTL_MINUTES")  # Default 1 hour
    GEMINI_CACHE_MIN_TOKENS: int = Field(4096, env="GEMINI_CACHE_MIN_TOKENS")  # Minimum tokens to cache
    GEMINI_CACHE_MAX_CACHED_SESSIONS: int = Field(1000, env="GEMINI_CACHE_MAX_CACHED_SESSIONS")
    GEMINI_CACHE_PERSISTENCE_TYPE: str = Field("sqlite", env="GEMINI_CACHE_PERSISTENCE_TYPE")  # sqlite, redis, or memory
    
    # 🔹 NEW: Redis Configuration (for distributed caching)
    REDIS_URL: Optional[str] = Field(None, env="REDIS_URL")
    REDIS_CACHE_DB: int = Field(1, env="REDIS_CACHE_DB")
    
    # 🔹 NEW: Streaming Configuration
    STREAMING_ENABLED: bool = Field(True, env="STREAMING_ENABLED")
    STREAM_CHUNK_SIZE: int = Field(10, env="STREAM_CHUNK_SIZE")  # Characters per chunk
    
    # Whisper STT config
    WHISPER_MODEL_SIZE: str = Field("small", env="WHISPER_MODEL_SIZE")
    WHISPER_DEVICE: str = Field("auto", env="WHISPER_DEVICE")
    MAX_AUDIO_SIZE_BYTES: int = Field(5_000_000, env="MAX_AUDIO_SIZE_BYTES")
    MAX_AUDIO_DURATION_SECONDS: int = Field(60, env="MAX_AUDIO_DURATION_SECONDS")
    SUPPORTED_AUDIO_MIME: list = Field(
        ["audio/wav", "audio/mpeg", "audio/ogg", "audio/webm"],
        env="SUPPORTED_AUDIO_MIME"
    )
    
    # Piper TTS config (includes Hindi voice)
    PIPER_VOICE_EN: str = Field("en_US-amy-medium", env="PIPER_VOICE_EN")
    PIPER_VOICE_ES: str = Field("es_AR-daniela-high", env="PIPER_VOICE_ES")
    PIPER_VOICE_FR: str = Field("fr_FR-siwis-medium", env="PIPER_VOICE_FR")
    PIPER_VOICE_DE: str = Field("de_DE-ramona-low", env="PIPER_VOICE_DE")
    PIPER_VOICE_IT: str = Field("it_IT-paola-medium", env="PIPER_VOICE_IT")
    PIPER_VOICE_PT: str = Field("es_AR-daniela-high", env="PIPER_VOICE_PT")
    PIPER_VOICE_ZH: str = Field("zh_CN-huayan-medium", env="PIPER_VOICE_ZH")
    PIPER_VOICE_SW: str = Field("sw_CD-lanfrica-medium", env="PIPER_VOICE_SW")
    PIPER_VOICE_HI: str = Field("hi_IN-priyamvada-medium", env="PIPER_VOICE_HI")  # 🇮🇳 Hindi added
  
    
    # Argos Translate config (includes Hindi)
    ARGOS_SUPPORTED_LANGUAGES: list = Field(
        ["en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko", "ar", "hi", "sw", "zh", "ru"],  # 🇮🇳 Added "hi"
        env="ARGOS_SUPPORTED_LANGUAGES"
    )
    
    # Clinical safety
    MAX_CONVERSATION_TURNS: int = Field(15, env="MAX_CONVERSATION_TURNS")
    CLINICAL_SUMMARY_MIN_SYMPTOMS: int = Field(3, env="CLINICAL_SUMMARY_MIN_SYMPTOMS")
    PROMPT_INJECTION_THRESHOLD: float = Field(0.7, env="PROMPT_INJECTION_THRESHOLD")
    
    # 🔹 NEW: Token Usage Tracking & Freemium Limits
    TOKEN_TRACKING_ENABLED: bool = Field(True, env="TOKEN_TRACKING_ENABLED")
    USAGE_DB_PATH: str = Field("/tmp/usage_tracking.db", env="USAGE_DB_PATH")
    TRACK_INDIVIDUAL_TOKENS: bool = Field(True, env="TRACK_INDIVIDUAL_TOKENS")  # Per-request granularity
    
    # Freemium tier default limits (tokens/month)
    DEFAULT_FREE_TIER_LIMIT: int = Field(10_000, env="DEFAULT_FREE_TIER_LIMIT")
    DEFAULT_PLUS_TIER_LIMIT: int = Field(50_000, env="DEFAULT_PLUS_TIER_LIMIT")
    DEFAULT_PRO_TIER_LIMIT: int = Field(100_000, env="DEFAULT_PRO_TIER_LIMIT")
    
    # Billing cycle (calendar month by default)
    BILLING_CYCLE_TYPE: str = Field("calendar_month", env="BILLING_CYCLE_TYPE")  # calendar_month or 30-day
    
    # 🔹 NEW: Database Configuration (Supabase PostgreSQL)
    DATABASE_URL: str = Field(..., env="DATABASE_URL")  # postgresql://user:password@host/db
    
    # 🔹 NEW: JWT Authentication Configuration
    JWT_SECRET_KEY: str = Field(..., env="JWT_SECRET_KEY")  # Must be set in environment
    JWT_ALGORITHM: str = Field("HS256", env="JWT_ALGORITHM")  # HMAC algorithm
    JWT_EXPIRATION_DAYS: int = Field(30, env="JWT_EXPIRATION_DAYS")  # Access token expiry in days
    JWT_REFRESH_EXPIRATION_DAYS: int = Field(90, env="JWT_REFRESH_EXPIRATION_DAYS")  # Refresh token expiry
    
    @validator("JWT_ALGORITHM", pre=True, always=True)
    def strip_jwt_algorithm(cls, v):
        """Strip whitespace from JWT algorithm to handle trailing spaces in env vars"""
        if v:
            return v.strip()
        return v
    
    # Cache directories (important for Hugging Face Spaces ephemeral storage)
    WHISPER_CACHE_DIR: str = Field("/tmp/whisper_cache", env="WHISPER_CACHE_DIR")
    ARGOS_MODELS_DIR: str = Field("/tmp/argos_models", env="ARGOS_MODELS_DIR")
    PIPER_VOICES_DIR: str = Field("/tmp/piper_voices", env="PIPER_VOICES_DIR")
    GEMINI_CACHE_DB_PATH: str = Field("/tmp/gemini_cache.db", env="GEMINI_CACHE_DB_PATH")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def piper_voices_map(self) -> dict:
        """Map language codes to Piper voice names (includes Hindi)"""
        return {
            "en": self.PIPER_VOICE_EN,
            "es": self.PIPER_VOICE_ES,
            "fr": self.PIPER_VOICE_FR,
            "de": self.PIPER_VOICE_DE,
            "it": self.PIPER_VOICE_IT,
            "pt": self.PIPER_VOICE_PT,
            "sw": self.PIPER_VOICE_SW,
            "zh": self.PIPER_VOICE_ZH,
            "hi": self.PIPER_VOICE_HI,  # 🇮🇳 Hindi added
            "default": self.PIPER_VOICE_EN
        }
    
    @property
    def argos_language_set(self) -> set:
        """Get supported languages as a set for fast lookup"""
        return set(self.ARGOS_SUPPORTED_LANGUAGES)
    
    @property
    def gemini_cache_ttl(self) -> timedelta:
        """Get cache TTL as timedelta"""
        return timedelta(minutes=self.GEMINI_CACHE_TTL_MINUTES)


@lru_cache()
def get_settings():
    """Cached settings instance for dependency injection"""
    return Settings()