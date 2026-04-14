"""
User Management Service
Handles user CRUD operations and authentication
"""
import uuid
import logging
from typing import Optional, Dict
from sqlalchemy.orm import Session
from app.db.models import User, UserTier
from app.services.auth_service import PasswordService, JWTAuthService

logger = logging.getLogger(__name__)


class UserService:
    """Manages user accounts and authentication"""
    
    def __init__(self, jwt_service: JWTAuthService):
        self.jwt_service = jwt_service
    
    def create_user(self, db: Session, email: str, password: str, tier: str = "free") -> User:
        """
        Create new user account.
        
        Args:
            db: Database session
            email: User email
            password: User password (will be hashed)
            tier: User tier (default: free)
        
        Returns:
            Created User object
        """
        # Check if user exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise ValueError(f"User with email {email} already exists")
        
        # Validate tier
        try:
            user_tier = UserTier(tier.lower())
        except ValueError:
            raise ValueError(f"Invalid tier: {tier}")
        
        # Create user
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=PasswordService.hash_password(password),
            tier=user_tier,
            monthly_token_limit=self._get_token_limit(user_tier)
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        logger.info(f"✅ Created user: {email} ({tier})")
        return user
    
    def authenticate_user(self, db: Session, email: str, password: str) -> Optional[User]:
        """
        Authenticate user with email and password.
        
        Args:
            db: Database session
            email: User email
            password: User password
        
        Returns:
            User object if authenticated, None otherwise
        """
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            logger.warning(f"Login attempt with non-existent email: {email}")
            return None
        
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {email}")
            return None
        
        if not PasswordService.verify_password(password, user.password_hash):
            logger.warning(f"Failed login attempt for user: {email}")
            return None
        
        logger.info(f"✅ User authenticated: {email}")
        return user
    
    def get_user_by_id(self, db: Session, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return db.query(User).filter(User.id == user_id).first()
    
    def get_user_by_email(self, db: Session, email: str) -> Optional[User]:
        """Get user by email"""
        return db.query(User).filter(User.email == email).first()
    
    def upgrade_user_tier(self, db: Session, user_id: str, new_tier: str) -> User:
        """
        Upgrade user to new tier.
        
        Args:
            db: Database session
            user_id: User ID
            new_tier: New tier (free, plus, pro, enterprise)
        
        Returns:
            Updated User object
        """
        user = self.get_user_by_id(db, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        try:
            tier_enum = UserTier(new_tier.lower())
        except ValueError:
            raise ValueError(f"Invalid tier: {new_tier}")
        
        old_tier = user.tier
        user.tier = tier_enum
        user.monthly_token_limit = self._get_token_limit(tier_enum)
        
        db.commit()
        db.refresh(user)
        
        logger.info(f"✅ User {user.email} upgraded from {old_tier} to {new_tier}")
        return user
    
    def get_current_usage(self, db: Session, user_id: str) -> int:
        """
        Get current month's token usage for user.
        
        Args:
            db: Database session
            user_id: User ID
        
        Returns:
            Total tokens used this month
        """
        from datetime import datetime
        from app.db.models import UsageRecord
        
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        result = db.query(UsageRecord).filter(
            UsageRecord.user_id == user_id,
            UsageRecord.timestamp >= current_month_start
        ).all()
        
        total = sum(r.total_billable_tokens for r in result)
        return total
    
    def create_tokens(self, user: User) -> Dict[str, str]:
        """
        Create access and refresh tokens for user.
        
        Args:
            user: User object
        
        Returns:
            Dict with access_token and refresh_token
        """
        access_token = self.jwt_service.create_access_token(
            user_id=user.id,
            email=user.email,
            tier=user.tier.value
        )
        
        refresh_token = self.jwt_service.create_refresh_token(user_id=user.id)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.jwt_service.expiration_days * 86400  # seconds
        }
    
    @staticmethod
    def _get_token_limit(tier: UserTier) -> int:
        """Get monthly token limit for tier"""
        limits = {
            UserTier.FREE: 10_000,
            UserTier.PLUS: 50_000,
            UserTier.PRO: 100_000,
            UserTier.ENTERPRISE: 1_000_000,
            UserTier.ADMIN: 10_000_000
        }
        return limits.get(tier, 10_000)


# Global instance
_user_service = None


def init_user_service(jwt_service: JWTAuthService) -> UserService:
    """Initialize user service"""
    global _user_service
    _user_service = UserService(jwt_service)
    return _user_service


def get_user_service() -> UserService:
    """Get user service instance"""
    if _user_service is None:
        raise RuntimeError("User service not initialized")
    return _user_service
