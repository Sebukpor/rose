"""
Freemium Usage Limiter - Enforces token quotas per user tier.
Integrates with usage tracking to control API access.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from enum import Enum
from app.services.usage_tracking import UsageDatabase, UsageStats

logger = logging.getLogger(__name__)


class UserTier(str, Enum):
    """Freemium tier definitions"""
    ADMIN = "admin"  # Unlimited
    ENTERPRISE = "enterprise"  # Unlimited
    PRO = "pro"  # 100K tokens/month
    PLUS = "plus"  # 50K tokens/month
    FREE = "free"  # 10K tokens/month


class TierLimits:
    """Token limits per tier (monthly)"""
    
    LIMITS: Dict[UserTier, int] = {
        UserTier.ADMIN: -1,  # Unlimited
        UserTier.ENTERPRISE: -1,  # Unlimited
        UserTier.PRO: 100_000,
        UserTier.PLUS: 50_000,
        UserTier.FREE: 10_000,
    }
    
    PRICING: Dict[UserTier, float] = {
        UserTier.ADMIN: 0.0,
        UserTier.ENTERPRISE: 999.99,  # Custom
        UserTier.PRO: 29.99,
        UserTier.PLUS: 14.99,
        UserTier.FREE: 0.0,
    }
    
    @classmethod
    def get_limit(cls, tier: UserTier) -> int:
        """Get monthly token limit for tier"""
        return cls.LIMITS.get(tier, cls.LIMITS[UserTier.FREE])
    
    @classmethod
    def get_price(cls, tier: UserTier) -> float:
        """Get monthly price for tier"""
        return cls.PRICING.get(tier, cls.PRICING[UserTier.FREE])


class QuotaExceededError(Exception):
    """Raised when user exceeds token quota"""
    
    def __init__(self, user_id: str, tokens_used: int, limit: int):
        self.user_id = user_id
        self.tokens_used = tokens_used
        self.limit = limit
        super().__init__(
            f"User {user_id} has exceeded quota: {tokens_used}/{limit} tokens used"
        )


class FreemiumLimiter:
    """Enforces freemium tier token limits"""
    
    def __init__(self, usage_db: UsageDatabase):
        self.db = usage_db
        logger.info("Freemium limiter initialized with token tracking")
    
    async def check_quota(self, user_id: str, tokens_needed: int) -> bool:
        """
        Check if user can consume tokens given their tier.
        
        Returns:
            True if user has sufficient quota
            
        Raises:
            QuotaExceededError if user would exceed limit
        """
        tier = await self._get_user_tier(user_id)
        limit = TierLimits.get_limit(tier)
        
        # Unlimited tiers pass all checks
        if limit < 0:
            logger.debug(f"User {user_id} ({tier}) has unlimited quota")
            return True
        
        # Get current usage in billing cycle
        current_usage = await self._get_current_cycle_usage(user_id)
        
        if current_usage + tokens_needed > limit:
            logger.warning(
                f"Quota exceeded for user {user_id}: "
                f"would use {current_usage + tokens_needed}/{limit} tokens"
            )
            raise QuotaExceededError(user_id, current_usage + tokens_needed, limit)
        
        logger.debug(
            f"Quota check passed for user {user_id}: "
            f"{current_usage + tokens_needed}/{limit} tokens"
        )
        return True
    
    async def get_usage_summary(self, user_id: str) -> Dict:
        """Get detailed usage summary for user"""
        tier = await self._get_user_tier(user_id)
        limit = TierLimits.get_limit(tier)
        current_usage = await self._get_current_cycle_usage(user_id)
        cycle_info = await self._get_billing_cycle(user_id)
        
        remaining = limit - current_usage if limit > 0 else -1
        percentage = (current_usage / limit * 100) if limit > 0 else 0
        
        return {
            "user_id": user_id,
            "tier": tier.value,
            "monthly_limit": limit,
            "current_usage": current_usage,
            "remaining": remaining,
            "percentage_used": round(percentage, 2),
            "billing_cycle_start": cycle_info["start"].isoformat(),
            "billing_cycle_end": cycle_info["end"].isoformat(),
            "days_remaining": (cycle_info["end"] - datetime.utcnow()).days,
            "price_per_month": TierLimits.get_price(tier),
            "unlimited": limit < 0
        }
    
    async def _get_user_tier(self, user_id: str) -> UserTier:
        """
        Get user's current tier.
        TODO: Integrate with actual user database/auth system
        """
        # Placeholder - query from user_quotas table when created
        # For now, default to FREE tier
        tier_str = "free"  # Will be fetched from database
        try:
            return UserTier(tier_str.lower())
        except ValueError:
            return UserTier.FREE
    
    async def _get_current_cycle_usage(self, user_id: str) -> int:
        """Get token usage in current billing cycle"""
        cycle_info = await self._get_billing_cycle(user_id)
        records = await self.db.get_user_usage(
            user_id, 
            days=(cycle_info["end"] - datetime.utcnow()).days + 1
        )
        
        total = sum(r.total_billable_tokens for r in records)
        logger.debug(f"Current cycle usage for {user_id}: {total} tokens")
        return total
    
    async def _get_billing_cycle(self, user_id: str) -> Dict[str, datetime]:
        """
        Get billing cycle start and end dates.
        Assumes monthly cycles starting on account creation or calendar month.
        """
        now = datetime.utcnow()
        
        # Simple implementation: calendar month
        cycle_start = datetime(now.year, now.month, 1)
        cycle_end = datetime(
            now.year if now.month < 12 else now.year + 1,
            now.month + 1 if now.month < 12 else 1,
            1
        ) - timedelta(seconds=1)
        
        return {
            "start": cycle_start,
            "end": cycle_end,
            "current_day": (now - cycle_start).days + 1,
            "total_days": (cycle_end - cycle_start).days + 1
        }
    
    async def set_user_tier(self, user_id: str, tier: UserTier) -> bool:
        """Set/update user's tier (admin only)"""
        logger.info(f"Setting user {user_id} tier to {tier}")
        # TODO: Implement database persistence
        return True
    
    async def reset_user_quota(self, user_id: str, reason: str = "") -> bool:
        """Reset user's quota for current cycle (admin override)"""
        logger.warning(f"Resetting quota for user {user_id}: {reason}")
        # TODO: Clear usage records or add override flag
        return True
    
    def get_tier_description(self, tier: UserTier) -> Dict:
        """Get human-readable tier information"""
        limit = TierLimits.get_limit(tier)
        return {
            "name": tier.value.capitalize(),
            "price": f"${TierLimits.get_price(tier):.2f}/month",
            "limit": "Unlimited" if limit < 0 else f"{limit:,} tokens/month",
            "use_cases": self._get_tier_use_cases(tier)
        }
    
    def _get_tier_use_cases(self, tier: UserTier) -> list[str]:
        """Get recommended use cases for tier"""
        use_cases = {
            UserTier.FREE: [
                "Individual use",
                "Testing & evaluation",
                "~10 patient sessions/month"
            ],
            UserTier.PLUS: [
                "Small clinic operations",
                "~50 patient sessions/month",
                "Priority support"
            ],
            UserTier.PRO: [
                "Medium clinic operations",
                "~200 patient sessions/month",
                "API access",
                "Custom integrations"
            ],
            UserTier.ENTERPRISE: [
                "Hospital systems",
                "Unlimited usage",
                "Dedicated support",
                "SLA guarantees"
            ],
            UserTier.ADMIN: ["Internal testing"]
        }
        return use_cases.get(tier, [])
