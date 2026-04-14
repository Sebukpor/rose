import logging
import os
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ------------------------------------------------------------------
# 🔧 CRITICAL FIX: Ensure project root is on PYTHONPATH
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from typing import Optional
from fastapi import Header, Query, Body

from app.services.usage_tracking import UsageDatabase
from app.services.usage_limiter import FreemiumLimiter, QuotaExceededError
from app.api.utils.usage_api import UsageAPIHandler

from app.core.config import get_settings
from app.core.prompt_loader import PromptLoader
from app.api.route.avatar import router as avatar_router
from app.api.route.auth import router as auth_router
from app.api.route.usage import router as usage_router
from app.models.response import ErrorResponse
from app.services.gemini_cache_manager import get_cache_manager
from app.db.database import DatabaseManager, init_db, get_db_manager
from app.db.models import Base
from app.services.auth_service import init_jwt_service, get_jwt_service
from app.services.user_service import init_user_service, get_user_service
from app.core.dependencies import (
    init_dependencies,
    get_usage_db,
    get_usage_limiter,
    get_usage_api_handler
)


# ------------------------------------------------------------------
# IST Timezone
# ------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))


class ISTFormatter(logging.Formatter):
    """Always stamps log records in IST (UTC+5:30)."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        ist_time = datetime.fromtimestamp(record.created, tz=IST)
        if datefmt:
            return ist_time.strftime(datefmt)
        return ist_time.strftime("%Y-%m-%dT%H:%M:%S IST")


# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------
def _build_handler(stream=sys.stdout) -> logging.StreamHandler:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        ISTFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S IST",
        )
    )
    return handler


usage_db: Optional[UsageDatabase] = None
usage_limiter: Optional[FreemiumLimiter] = None
usage_api_handler: Optional[UsageAPIHandler] = None

# 🔹 NEW: Supabase & JWT globals
db_manager: Optional[DatabaseManager] = None


# Root logger — all libraries inherit IST stamps
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()
root_logger.addHandler(_build_handler())

# Dedicated audit logger (write to its own file in production if needed)
audit_logger = logging.getLogger("rose.audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = True          # still flows to root (stdout)

logger = logging.getLogger("rose.startup")

settings = get_settings()

# Import shared instances from dependencies module
# These are initialized in the lifespan context manager


# ------------------------------------------------------------------
# Audit helpers
# ------------------------------------------------------------------

def _now_ist() -> str:
    return datetime.now(tz=IST).strftime("%Y-%m-%dT%H:%M:%S IST")


def log_model_response(
    *,
    request_id: str,
    endpoint: str,
    session_id: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None,
    latency_ms: float,
    finish_reason: str | None,
    safety_ratings: list | None,
    streaming: bool,
    cache_hit: bool,
    error: str | None = None,
) -> None:
    """
    Emit one structured audit line per Gemini inference call.

    Keep fields stable — downstream log-aggregators (Loki, CloudWatch,
    Datadog) parse this exact format.  Never log patient text here.
    """
    audit_logger.info(
        "GEMINI_RESPONSE | "
        "request_id=%(request_id)s | "
        "endpoint=%(endpoint)s | "
        "session_id=%(session_id)s | "
        "input_tokens=%(input_tokens)s | "
        "output_tokens=%(output_tokens)s | "
        "cached_tokens=%(cached_tokens)s | "
        "latency_ms=%(latency_ms).1f | "
        "finish_reason=%(finish_reason)s | "
        "safety_ratings=%(safety_ratings)s | "
        "streaming=%(streaming)s | "
        "cache_hit=%(cache_hit)s | "
        "error=%(error)s | "
        "ts=%(ts)s",
        {
            "request_id": request_id,
            "endpoint": endpoint,
            "session_id": session_id or "anon",
            "input_tokens": input_tokens if input_tokens is not None else "N/A",
            "output_tokens": output_tokens if output_tokens is not None else "N/A",
            "cached_tokens": cached_tokens if cached_tokens is not None else "N/A",
            "latency_ms": latency_ms,
            "finish_reason": finish_reason or "N/A",
            "safety_ratings": safety_ratings or [],
            "streaming": streaming,
            "cache_hit": cache_hit,
            "error": error or "none",
            "ts": _now_ist(),
        },
    )


# ------------------------------------------------------------------
# Lifespan: hard safety validation before accepting traffic
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    cache_manager = None
    try:
        # --- Gemini API key ---
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        # --- Prompts ---
        prompt_loader = PromptLoader(settings.PROMPTS_DIR)
        rose_prompt = prompt_loader.get_rose_prompt()
        clinical_prompt = prompt_loader.get_clinical_summary_prompt()

        if not rose_prompt:
            raise FileNotFoundError("ROSE system prompt missing or empty")
        if not clinical_prompt:
            raise FileNotFoundError("Clinical summary prompt missing or empty")

        # --- ffmpeg ---
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
            check=True,
        )
        logger.info("✅ ffmpeg verified")

        # --- Whisper ---
        import torch
        from faster_whisper import WhisperModel
        import numpy as np

        device = (
            "cuda"
            if torch.cuda.is_available() and settings.WHISPER_DEVICE != "cpu"
            else "cpu"
        )
        compute_type = "float16" if device == "cuda" else "int8"

        logger.info(f"Loading Whisper model '{settings.WHISPER_MODEL_SIZE}' on {device}")
        model = WhisperModel(
            settings.WHISPER_MODEL_SIZE,
            device=device,
            compute_type=compute_type,
            download_root=settings.WHISPER_CACHE_DIR,
        )

        dummy_audio = np.zeros(16000, dtype=np.float32)
        segments, info = model.transcribe(dummy_audio, beam_size=1)
        logger.info(f"✅ Whisper ready (lang={info.language})")

        # --- Argos Translate ---
        import argostranslate.package
        import argostranslate.translate

        argostranslate.package.update_package_index()
        installed = argostranslate.translate.get_installed_languages()
        if installed:
            logger.info(
                "✅ Argos Translate languages: "
                + ", ".join(lang.code for lang in installed)
            )
        else:
            logger.warning("⚠️ No Argos models installed (will download on first use)")

        # --- Piper TTS (optional) ---
        try:
            subprocess.run(
                ["piper", "--version"], capture_output=True, timeout=3, check=True
            )
            logger.info("✅ Piper TTS available")
        except Exception:
            logger.warning("⚠️ Piper TTS not found (optional dependency)")

        # --- Gemini Context Cache Manager ---
        if settings.GEMINI_CACHE_ENABLED:
            cache_manager = await get_cache_manager()
            stats = await cache_manager.get_cache_stats()
            logger.info(f"✅ Gemini Context Cache initialized: {stats['backend_type']}")
            logger.info(f"   Cache TTL: {settings.GEMINI_CACHE_TTL_MINUTES} minutes")
            logger.info(f"   Min tokens: {settings.GEMINI_CACHE_MIN_TOKENS}")

        # --- 🔹 NEW: Token Usage Tracking ---
        global db_manager, usage_db, usage_limiter, usage_api_handler
        if settings.TOKEN_TRACKING_ENABLED:
            try:
                # Initialize shared dependencies
                usage_db, usage_limiter, usage_api_handler = init_dependencies(settings.USAGE_DB_PATH)
                
                logger.info("✅ Token tracking and freemium quotas initialized")
                logger.info(f"   Database: {settings.USAGE_DB_PATH}")
                logger.info(f"   FREE tier: {settings.DEFAULT_FREE_TIER_LIMIT:,} tokens/month")
                logger.info(f"   PLUS tier: {settings.DEFAULT_PLUS_TIER_LIMIT:,} tokens/month")
                logger.info(f"   PRO tier: {settings.DEFAULT_PRO_TIER_LIMIT:,} tokens/month")
            except Exception as e:
                logger.error(f"Failed to initialize usage tracking: {e}")
                usage_db = None
                usage_limiter = None
                usage_api_handler = None

        # --- 🔹 NEW: Supabase Database Initialization ---
        try:
            db_manager = init_db(settings.DATABASE_URL)
            db_manager.create_all_tables(Base)
            logger.info("✅ Supabase connection initialized")
            logger.info(f"   Database URL: {settings.DATABASE_URL[:50]}...")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase connection: {e}")
            raise

        # --- 🔹 NEW: JWT Service Initialization ---
        try:
            jwt_service = init_jwt_service(
                secret_key=settings.JWT_SECRET_KEY,
                algorithm=settings.JWT_ALGORITHM,
                expiration_days=settings.JWT_EXPIRATION_DAYS
            )
            logger.info("✅ JWT authentication service initialized")
            logger.info(f"   Algorithm: {settings.JWT_ALGORITHM}")
            logger.info(f"   Expiration: {settings.JWT_EXPIRATION_DAYS} days")
        except Exception as e:
            logger.error(f"Failed to initialize JWT service: {e}")
            raise

        # --- 🔹 NEW: User Service Initialization ---
        try:
            user_service = init_user_service(jwt_service)
            logger.info("✅ User management service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize user service: {e}")
            raise

        # --- Final summary (model name stays server-side) ---
        logger.info("✅✅✅ ROSE startup validation SUCCESSFUL")
        logger.info(f"Environment     : {settings.ENVIRONMENT}")
        logger.info(f"Whisper model   : {settings.WHISPER_MODEL_SIZE}")
        logger.info(f"Streaming       : {'enabled' if settings.STREAMING_ENABLED else 'disabled'}")
        logger.info(f"Context Caching : {'enabled' if settings.GEMINI_CACHE_ENABLED else 'disabled'}")
        logger.info(f"Token Tracking  : {'enabled' if settings.TOKEN_TRACKING_ENABLED else 'disabled'}")
        # ⬆️  settings.GEMINI_MODEL intentionally omitted from logs & responses

        yield

    except Exception as e:
        logger.critical(f"❌ Startup validation FAILED: {e}", exc_info=True)
        sys.exit(1)

    finally:
        # --- 🔹 NEW: Cleanup database connection ---
        if db_manager:
            try:
                db_manager.close()
                logger.info("✅ Supabase connection closed gracefully")
            except Exception as e:
                logger.warning(f"Error closing database connection: {e}")

        # --- 🔹 NEW: Cleanup usage database ---
        if usage_db:
            try:
                deleted = await usage_db.cleanup_old_records(days=90)
                logger.info(f"✅ Cleaned up {deleted} usage records older than 90 days")
            except Exception as e:
                logger.warning(f"Error during usage database cleanup: {e}")

        if cache_manager:
            try:
                await cache_manager.stop()
                logger.info("✅ Cache manager stopped gracefully")
            except Exception as e:
                logger.warning(f"Error stopping cache manager: {e}")

        logger.info("Shutdown initiated")


# ------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------
app = FastAPI(
    title="ROSE Clinical Triage Engine",
    description="Production-grade clinical triage backend for ROSE avatar.",
    version="1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ------------------------------------------------------------------
# Audit middleware — attaches request_id, measures wall-clock time
# ------------------------------------------------------------------
@app.middleware("http")
async def audit_middleware(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    request.state.started_at = time.perf_counter()

    # Propagate request_id downstream so service layers can stamp it
    request.state.audit_log = log_model_response

    response: Response = await call_next(request)

    elapsed_ms = (time.perf_counter() - request.state.started_at) * 1000

    # Lightweight HTTP-level audit (no PHI)
    logger.info(
        "HTTP | request_id=%s | %s %s | status=%s | %.1f ms",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )

    response.headers["X-Request-Id"] = request_id
    response.headers["X-Clinical-Safety-Protocol"] = "ROSE_v1.0"
    return response


# ------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------
origins = (
    [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    if settings.CORS_ORIGINS
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Clinical-Safety-Protocol", "X-Request-Id"],
)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.get("/health", tags=["Monitoring"])
async def health():
    """
    Liveness + readiness probe.
    Deliberately excludes the underlying model name from the response.
    """
    cache_status = "enabled" if settings.GEMINI_CACHE_ENABLED else "disabled"
    return {
        "status": "healthy",
        "service": "rose-triage-engine",
        "version": "1.0",
        "environment": settings.ENVIRONMENT,
        "safety_protocol": "ROSE_v1.0",
        "features": {
            "context_caching": cache_status,
            "streaming": settings.STREAMING_ENABLED,
            "multimodal": True,
        },
        # model name intentionally absent
    }


# ------------------------------------------------------------------
# Exception handlers
# ------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="client_error",
            message=exc.detail,
            suggestion="Check API schema at /docs",
            reference_id=f"ROSE-{request_id[:8].upper()}",
        ).dict(),
        headers={
            "X-Clinical-Safety-Protocol": "ROSE_v1.0",
            "X-Request-Id": request_id,
        },
    )


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", os.urandom(4).hex().upper())
    logger.error(
        "Unhandled exception | request_id=%s | %s",
        request_id,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="clinical_safety",
            message="Clinical safety protocol activated.",
            suggestion="Contact clinical support",
            reference_id=f"ROSE-{request_id[:8].upper()}",
        ).dict(),
        headers={
            "X-Clinical-Safety-Protocol": "ROSE_v1.0",
            "X-Request-Id": request_id,
        },
    )


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
app.include_router(
    auth_router,
    tags=["Authentication"],
)

app.include_router(
    avatar_router,
    prefix="/api/v1/avatar",
    tags=["Clinical Triage"],
)

app.include_router(
    usage_router,
    tags=["Usage Tracking"],
)

# Deprecated: Old usage endpoints (kept for backward compatibility, will be removed in v2.0)
# Use /api/v1/usage/* endpoints instead which extract user_id from JWT automatically
# These legacy endpoints require User-Id header - new endpoints use JWT claims

@app.get("/api/v1/usage/status", tags=["Usage Tracking - Legacy"], deprecated=True)
async def get_usage_status_legacy(user_id: str = Header(None, alias="User-Id")):
    """
    [DEPRECATED] Get user's current quota status and usage.
    
    ⚠️ DEPRECATED: Use GET /api/v1/usage/status instead.
    New endpoint extracts user_id from JWT token automatically.
    
    Headers:
        User-Id: User identifier (required)
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="User-Id header required")
    
    if not usage_api_handler:
        raise HTTPException(status_code=503, detail="Usage tracking not available")
    
    try:
        result = await usage_api_handler.get_quota_status(user_id)
        return result
    except Exception as e:
        logger.error(f"Error getting quota status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve quota status")


@app.get("/api/v1/usage/history", tags=["Usage Tracking - Legacy"], deprecated=True)
async def get_usage_history_legacy(
    user_id: str = Header(None, alias="User-Id"),
    days: int = Query(30, ge=1, le=365, description="Days of history to retrieve")
):
    """
    [DEPRECATED] Get detailed usage history for user.
    
    ⚠️ DEPRECATED: Use GET /api/v1/usage/history instead.
    New endpoint extracts user_id from JWT token automatically and supports pagination.
    
    Headers:
        User-Id: User identifier (required)
    
    Query Parameters:
        days: Number of days to look back (1-365, default 30)
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="User-Id header required")
    
    if not usage_api_handler:
        raise HTTPException(status_code=503, detail="Usage tracking not available")
    
    try:
        result = await usage_api_handler.get_user_usage(user_id, days=days)
        return result
    except Exception as e:
        logger.error(f"Error getting usage history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve usage history")


@app.get("/api/v1/pricing/tiers", tags=["Usage Tracking - Legacy"], deprecated=True)
async def get_pricing_tiers_legacy(tier: Optional[str] = Query(None, description="Specific tier to get info for")):
    """
    [DEPRECATED] Get pricing tier information and limits.
    
    ⚠️ DEPRECATED: Use GET /api/v1/usage/tiers instead.
    """
    if not usage_api_handler:
        raise HTTPException(status_code=503, detail="Usage tracking not available")
    
    try:
        result = await usage_api_handler.get_tier_info(tier)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tier info: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve tier information")



# ================================================================
# 🔹 NEW: Usage Tracking & Quota Management Endpoints
# ================================================================
async def root():
    return {
        "service": "ROSE Clinical Triage Engine",
        "version": "1.0",
        "docs": "/docs",
        "health": "/health",
        "boundary": "NO_DIAGNOSIS_NO_PRESCRIPTIONS",
        "features": ["context-caching", "streaming", "multimodal"],
        # model name intentionally absent
    }


# ------------------------------------------------------------------
# Local / HF entrypoint
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        log_level="info",
        reload=False,
        workers=1,
    )