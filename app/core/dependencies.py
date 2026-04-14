"""
Shared dependencies and service instances.
This module prevents circular imports between main.py and route modules.
Instances are created lazily to allow configuration loading first.
"""
from app.services.usage_limiter import FreemiumLimiter
from app.api.utils.usage_api import UsageAPIHandler
from app.services.usage_tracking import UsageDatabase

# Lazy initialization - will be set by main.py during startup
_usage_db = None
_usage_limiter = None
_usage_api_handler = None


def get_usage_db():
    """Get the shared UsageDatabase instance"""
    global _usage_db
    if _usage_db is None:
        raise RuntimeError("UsageDatabase not initialized. Call init_dependencies() first.")
    return _usage_db


def get_usage_limiter():
    """Get the shared FreemiumLimiter instance"""
    global _usage_limiter
    if _usage_limiter is None:
        raise RuntimeError("FreemiumLimiter not initialized. Call init_dependencies() first.")
    return _usage_limiter


def get_usage_api_handler():
    """Get the shared UsageAPIHandler instance"""
    global _usage_api_handler
    if _usage_api_handler is None:
        raise RuntimeError("UsageAPIHandler not initialized. Call init_dependencies() first.")
    return _usage_api_handler


def init_dependencies(db_path: str):
    """Initialize all shared dependencies with the given database path"""
    global _usage_db, _usage_limiter, _usage_api_handler
    
    _usage_db = UsageDatabase(db_path)
    _usage_limiter = FreemiumLimiter(usage_db=_usage_db)
    _usage_api_handler = UsageAPIHandler(usage_db=_usage_db, limiter=_usage_limiter)
    
    return _usage_db, _usage_limiter, _usage_api_handler
