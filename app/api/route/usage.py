"""
Usage Management Endpoints
Provides endpoints for quota monitoring, usage history, and tier management.
Addresses limitation: User-Id extracted from JWT (no redundant header required)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from app.db.models import User, UserTier
from app.api.dependencies import get_current_user, get_current_admin
from app.services.user_service import get_user_service
from app.api.utils.usage_api import UsageAPIHandler
from app.main import usage_api_handler, usage_limiter
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/usage", tags=["Usage Tracking"])


class UsageHistoryResponse(BaseModel):
    """Paginated usage history response"""
    user_id: str
    period_days: int
    total_tokens: int
    total_requests: int
    page: int
    page_size: int
    total_pages: int
    has_more: bool
    requests_by_endpoint: dict
    requests_by_date: dict
    records: List[dict]


class QuotaStatusResponse(BaseModel):
    """Current quota status"""
    status: str
    data: dict


class TierUpgradeRequest(BaseModel):
    """Request to upgrade user tier"""
    new_tier: str = Field(..., description="Target tier: free, plus, pro, enterprise")


class TierUpgradeResponse(BaseModel):
    """Tier upgrade result"""
    success: bool
    user_id: str
    old_tier: str
    new_tier: str
    message: str


class PricingTierInfo(BaseModel):
    """Information about a pricing tier"""
    name: str
    monthly_token_limit: int
    features: List[str]
    description: str


@router.get("/status", response_model=QuotaStatusResponse)
async def get_usage_status(current_user: User = Depends(get_current_user)):
    """
    Get current user's quota status and usage.
    
    🔹 IMPROVED: User-Id extracted from JWT token automatically.
    No need to pass User-Id header separately.
    
    Returns:
        Current quota status including:
        - tier: User's current tier
        - monthly_limit: Monthly token limit
        - tokens_used: Tokens used this billing cycle
        - tokens_remaining: Remaining tokens
        - percentage_used: Usage percentage
        - reset_date: When quota resets
        - is_limited: Whether user is currently rate-limited
    """
    if not usage_api_handler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage tracking not available"
        )
    
    try:
        result = await usage_api_handler.get_quota_status(current_user.id)
        return result
    except Exception as e:
        logger.error(f"Error getting quota status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve quota status"
        )


@router.get("/history", response_model=UsageHistoryResponse)
async def get_usage_history(
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=365, description="Days of history to retrieve"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    page_size: int = Query(50, ge=10, le=100, description="Items per page")
):
    """
    Get detailed usage history for current user.
    
    🔹 IMPROVED: 
    - User-Id extracted from JWT token automatically
    - Added pagination support (page, page_size parameters)
    - Returns total_pages and has_more for UI pagination
    
    Query Parameters:
        days: Number of days to look back (1-365, default 30)
        page: Page number for pagination (default 1)
        page_size: Number of items per page (10-100, default 50)
    
    Returns:
        Paginated usage history with:
        - Total tokens and requests
        - Breakdown by endpoint and date
        - Individual usage records (paginated)
        - Pagination metadata (total_pages, has_more)
    """
    if not usage_api_handler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage tracking not available"
        )
    
    try:
        # Get all records first
        records = await usage_api_handler.db.get_user_usage(current_user.id, days=days)
        
        if not records:
            return UsageHistoryResponse(
                user_id=current_user.id,
                period_days=days,
                total_tokens=0,
                total_requests=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                has_more=False,
                requests_by_endpoint={},
                requests_by_date={},
                records=[]
            )
        
        # Calculate totals
        total_tokens = sum(r.total_billable_tokens for r in records)
        total_requests = len(records)
        
        # Apply pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_records = records[start_idx:end_idx]
        
        # Calculate pagination metadata
        total_pages = (total_requests + page_size - 1) // page_size
        
        return UsageHistoryResponse(
            user_id=current_user.id,
            period_days=days,
            total_tokens=total_tokens,
            total_requests=total_requests,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_more=end_idx < total_requests,
            requests_by_endpoint=usage_api_handler._group_by_endpoint(records),
            requests_by_date=usage_api_handler._group_by_date(records),
            records=[r.to_dict() for r in paginated_records]
        )
    except Exception as e:
        logger.error(f"Error getting usage history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage history"
        )


@router.get("/history/admin/{target_user_id}", response_model=UsageHistoryResponse)
async def get_admin_usage_history(
    target_user_id: str,
    current_user: User = Depends(get_current_admin),
    days: int = Query(30, ge=1, le=365, description="Days of history to retrieve"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    page_size: int = Query(50, ge=10, le=100, description="Items per page")
):
    """
    Admin endpoint: Get usage history for any user.
    
    Requires admin privileges. Useful for support and analytics.
    
    Path Parameters:
        target_user_id: ID of the user to query
    
    Query Parameters:
        days: Number of days to look back (1-365, default 30)
        page: Page number for pagination (default 1)
        page_size: Number of items per page (10-100, default 50)
    """
    if not usage_api_handler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage tracking not available"
        )
    
    try:
        records = await usage_api_handler.db.get_user_usage(target_user_id, days=days)
        
        if not records:
            return UsageHistoryResponse(
                user_id=target_user_id,
                period_days=days,
                total_tokens=0,
                total_requests=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                has_more=False,
                requests_by_endpoint={},
                requests_by_date={},
                records=[]
            )
        
        total_tokens = sum(r.total_billable_tokens for r in records)
        total_requests = len(records)
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_records = records[start_idx:end_idx]
        
        total_pages = (total_requests + page_size - 1) // page_size
        
        return UsageHistoryResponse(
            user_id=target_user_id,
            period_days=days,
            total_tokens=total_tokens,
            total_requests=total_requests,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_more=end_idx < total_requests,
            requests_by_endpoint=usage_api_handler._group_by_endpoint(records),
            requests_by_date=usage_api_handler._group_by_date(records),
            records=[r.to_dict() for r in paginated_records]
        )
    except Exception as e:
        logger.error(f"Error getting admin usage history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage history"
        )


@router.post("/tier/upgrade", response_model=TierUpgradeResponse)
async def upgrade_tier(
    request: TierUpgradeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Upgrade user's subscription tier.
    
    🔹 NEW ENDPOINT: Allows users to upgrade their tier.
    In production, this should integrate with payment gateway (Stripe, Razorpay).
    For now, validates tier and updates database.
    
    Request Body:
        new_tier: Target tier (free, plus, pro, enterprise)
    
    Returns:
        Success status and tier information
    
    Note: 
        - Downgrades are not allowed via this endpoint (contact support)
        - Enterprise tier requires admin approval
        - Proration is not implemented yet
    """
    if not usage_limiter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage tracking not available"
        )
    
    # Validate tier
    valid_tiers = ["free", "plus", "pro", "enterprise"]
    if request.new_tier.lower() not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier. Must be one of: {', '.join(valid_tiers)}"
        )
    
    # Prevent downgrades through this endpoint
    tier_order = {"free": 0, "plus": 1, "pro": 2, "enterprise": 3}
    current_tier_value = current_user.tier.value
    new_tier_value = request.new_tier.lower()
    
    if tier_order.get(new_tier_value, 0) < tier_order.get(current_tier_value, 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot downgrade tier via this endpoint. Contact support for downgrades."
        )
    
    # Enterprise tier requires admin approval
    if new_tier_value == "enterprise" and current_user.tier != UserTier.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enterprise tier requires admin approval. Contact support."
        )
    
    try:
        # Get user service to update tier in database
        user_service = get_user_service()
        from app.db.database import get_db
        from fastapi import Depends
        
        # This is a simplified version - in production, you'd inject the DB session properly
        db = next(get_db())
        try:
            old_tier = current_user.tier.value
            
            # Update user tier in database
            updated_user = user_service.update_user_tier(
                db=db,
                user_id=current_user.id,
                new_tier=request.new_tier.lower()
            )
            
            # Update limiter cache
            await usage_limiter.set_user_tier(current_user.id, UserTier(request.new_tier.lower()))
            
            message = f"Successfully upgraded from {old_tier} to {request.new_tier.lower()}"
            if request.new_tier.lower() == "enterprise":
                message += " (pending admin approval)"
            
            return TierUpgradeResponse(
                success=True,
                user_id=current_user.id,
                old_tier=old_tier,
                new_tier=request.new_tier.lower(),
                message=message
            )
        finally:
            db.close()
            
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error upgrading tier: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upgrade tier"
        )


@router.get("/tiers", response_model=dict)
async def get_pricing_tiers(tier: Optional[str] = Query(None, description="Specific tier to get info for")):
    """
    Get pricing tier information and limits.
    
    Query Parameters:
        tier: Optional specific tier (free, plus, pro, enterprise, admin)
    
    Returns:
        Tier information including:
        - monthly_token_limit
        - features
        - description
        - overage_policy
    """
    if not usage_api_handler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage tracking not available"
        )
    
    try:
        result = await usage_api_handler.get_tier_info(tier)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tier info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tier information"
        )


@router.get("/check")
async def check_quota_available(
    tokens_needed: int = Query(..., gt=0, description="Number of tokens to check"),
    current_user: User = Depends(get_current_user)
):
    """
    Check if user has sufficient quota for a planned operation.
    
    Useful before starting expensive operations like long conversations
    or large document processing.
    
    Query Parameters:
        tokens_needed: Estimated tokens needed for the operation
    
    Returns:
        - available: Boolean indicating if quota is sufficient
        - tokens_needed: The requested amount
        - summary: Current usage summary
        - error: Error message if not available
    """
    if not usage_api_handler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage tracking not available"
        )
    
    try:
        result = await usage_api_handler.check_quota_available(
            current_user.id, 
            tokens_needed
        )
        return result
    except Exception as e:
        logger.error(f"Error checking quota: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check quota"
        )
