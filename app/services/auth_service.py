"""
JWT Authentication Service
Handles token generation, verification, and user authentication
"""
import jwt
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from passlib.context import CryptContext
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class JWTAuthService:
    """Manages JWT token creation and verification"""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256", expiration_days: int = 30):
        """
        Initialize JWT auth service.
        
        Args:
            secret_key: Secret key for signing tokens
            algorithm: JWT algorithm (default: HS256)
            expiration_days: Token expiration in days
        """
        if not secret_key or len(secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.expiration_days = expiration_days
        logger.info(f"✅ JWT auth service initialized (exp={expiration_days} days)")
    
    def create_access_token(self, user_id: str, email: str, tier: str) -> str:
        """
        Create JWT access token.
        
        Args:
            user_id: User UUID
            email: User email
            tier: User tier (free, plus, pro, enterprise, admin)
        
        Returns:
            JWT token string
        """
        payload = {
            "user_id": user_id,
            "email": email,
            "tier": tier,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(days=self.expiration_days),
            "type": "access"
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        logger.debug(f"Created access token for {email}")
        return token
    
    def create_refresh_token(self, user_id: str) -> str:
        """
        Create JWT refresh token (longer expiration).
        
        Args:
            user_id: User UUID
        
        Returns:
            JWT refresh token string
        """
        payload = {
            "user_id": user_id,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(days=90),  # 90 days
            "type": "refresh"
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        logger.debug(f"Created refresh token for {user_id}")
        return token
    
    def verify_token(self, token: str, token_type: str = "access") -> Dict:
        """
        Verify and decode JWT token.
        
        Args:
            token: JWT token string
            token_type: "access" or "refresh"
        
        Returns:
            Decoded payload dictionary
        
        Raises:
            HTTPException if token is invalid or expired
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Verify token type
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type. Expected {token_type}"
                )
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
    
    def get_user_from_token(self, token: str) -> Dict:
        """
        Extract user info from token.
        
        Args:
            token: JWT token string
        
        Returns:
            Dict with user_id, email, tier
        """
        payload = self.verify_token(token)
        return {
            "user_id": payload.get("user_id"),
            "email": payload.get("email"),
            "tier": payload.get("tier")
        }


class PasswordService:
    """Manages password hashing and verification"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using bcrypt"""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        return pwd_context.verify(plain_password, hashed_password)


# Global instance
_jwt_service = None


def init_jwt_service(secret_key: str, algorithm: str = "HS256", expiration_days: int = 30) -> JWTAuthService:
    """Initialize JWT service"""
    global _jwt_service
    _jwt_service = JWTAuthService(secret_key, algorithm, expiration_days)
    return _jwt_service


def get_jwt_service() -> JWTAuthService:
    """Get JWT service instance"""
    if _jwt_service is None:
        raise RuntimeError("JWT service not initialized")
    return _jwt_service
