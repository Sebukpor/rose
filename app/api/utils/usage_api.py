"""
Usage Tracking API Utilities - Provides endpoints for quota and usage management.
Integrates with FastAPI routes for monitoring and control.
"""
import logging
from typing import Optional
from fastapi import HTTPException, status
from app.services.usage_tracking import UsageDatabase, UsageRecord
from app.services.usage_limiter import FreemiumLimiter, UserTier, QuotaExceededError
from datetime import datetime

logger = logging.getLogger(__name__)


class UsageAPIHandler:
    """Handles API endpoints for usage tracking and quota management"""
    
    def __init__(self, usage_db: UsageDatabase, limiter: FreemiumLimiter):
        self.db = usage_db
        self.limiter = limiter
    
    async def get_user_usage(self, user_id: str, days: int = 30) -> dict:
        """Get detailed usage breakdown for a user"""
        records = await self.db.get_user_usage(user_id, days=days)
        
        if not records:
            return {
                "user_id": user_id,
                "total_tokens": 0,
                "total_requests": 0,
                "records": []
            }
        
        total_tokens = sum(r.total_billable_tokens for r in records)
        total_requests = len(records)
        
        return {
            "user_id": user_id,
            "period_days": days,
            "total_tokens": total_tokens,
            "total_requests": total_requests,
            "requests_by_endpoint": self._group_by_endpoint(records),
            "requests_by_date": self._group_by_date(records),
            "records": [r.to_dict() for r in records[:100]]  # Last 100 records
        }
    
    async def get_quota_status(self, user_id: str) -> dict:
        """Get current quota status for a user"""
        try:
            summary = await self.limiter.get_usage_summary(user_id)
            return {
                "status": "ok",
                "data": summary
            }
        except Exception as e:
            logger.error(f"Error getting quota status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve quota status"
            )
    
    async def check_quota_available(self, user_id: str, tokens_needed: int) -> dict:
        """Check if user can consume tokens"""
        try:
            await self.limiter.check_quota(user_id, tokens_needed)
            summary = await self.limiter.get_usage_summary(user_id)
            return {
                "available": True,
                "tokens_needed": tokens_needed,
                "summary": summary
            }
        except QuotaExceededError as e:
            return {
                "available": False,
                "error": str(e),
                "tokens_needed": tokens_needed,
                "summary": await self.limiter.get_usage_summary(user_id)
            }
        except Exception as e:
            logger.error(f"Error checking quota: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to check quota"
            )
    
    async def record_usage(self, user_id: str, session_id: str, endpoint: str, 
                         token_usage, cache_hit: bool = False, error: Optional[str] = None) -> int:
        """Record token usage for a request"""
        record = UsageRecord(
            user_id=user_id,
            session_id=session_id,
            endpoint=endpoint,
            input_tokens=token_usage.input_tokens if token_usage else 0,
            output_tokens=token_usage.output_tokens if token_usage else 0,
            cached_tokens=token_usage.cached_tokens if token_usage else 0,
            total_billable_tokens=token_usage.total_tokens if token_usage else 0,
            timestamp=datetime.utcnow(),
            cache_hit=cache_hit,
            error=error
        )
        
        record_id = await self.db.record_usage(record)
        logger.info(f"Recorded usage: user={user_id}, tokens={token_usage.total_tokens if token_usage else 0}")
        return record_id
    
    async def get_tier_info(self, tier: str = None) -> dict:
        """Get pricing and feature information for tiers"""
        if tier:
            try:
                tier_enum = UserTier(tier.lower())
                info = self.limiter.get_tier_description(tier_enum)
                return {"tier": tier, "info": info}
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unknown tier: {tier}")
        
        # Return all tiers
        all_tiers = {}
        for tier in UserTier:
            all_tiers[tier.value] = self.limiter.get_tier_description(tier)
        
        return {"tiers": all_tiers}
    
    async def upgrade_user_tier(self, user_id: str, new_tier: str) -> dict:
        """Upgrade user to a new tier (admin endpoint)"""
        try:
            tier_enum = UserTier(new_tier.lower())
            success = await self.limiter.set_user_tier(user_id, tier_enum)
            return {
                "success": success,
                "user_id": user_id,
                "new_tier": new_tier.lower()
            }
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {new_tier}")
    
    def _group_by_endpoint(self, records) -> dict:
        """Group usage records by endpoint"""
        grouped = {}
        for record in records:
            if record.endpoint not in grouped:
                grouped[record.endpoint] = {"requests": 0, "tokens": 0}
            grouped[record.endpoint]["requests"] += 1
            grouped[record.endpoint]["tokens"] += record.total_billable_tokens
        return grouped
    
    def _group_by_date(self, records) -> dict:
        """Group usage records by date"""
        grouped = {}
        for record in records:
            date_key = record.timestamp.strftime("%Y-%m-%d")
            if date_key not in grouped:
                grouped[date_key] = {"requests": 0, "tokens": 0}
            grouped[date_key]["requests"] += 1
            grouped[date_key]["tokens"] += record.total_billable_tokens
        return grouped
