"""
FastAPI Dependencies for Authentication
Provides dependency functions for protected endpoints
"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from starlette.authentication import AuthenticationError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.auth_service import get_jwt_service
from app.services.user_service import get_user_service
from app.db.models import User, UserTier

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Extract current user from JWT token.
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        db: Database session
    
    Returns:
        Authenticated User object
    
    Raises:
        HTTPException: 401 if token invalid or user not found
    """
    jwt_service = get_jwt_service()
    
    try:
        payload = jwt_service.verify_token(credentials.credentials, token_type="access")
    except HTTPException as e:
        raise e
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user_id",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user_service = get_user_service()
    user = user_service.get_user_by_id(db, user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated"
        )
    
    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency for admin-only endpoints.
    
    Args:
        current_user: Current authenticated user
    
    Returns:
        User if they are admin
    
    Raises:
        HTTPException: 403 if user is not admin
    """
    if current_user.tier != UserTier.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return current_user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Extract current user from JWT token (optional).
    Returns None if no token provided.
    
    Args:
        credentials: Optional HTTP Bearer token
        db: Database session
    
    Returns:
        User object if authenticated, None otherwise
    """
    if not credentials:
        return None
    
    jwt_service = get_jwt_service()
    
    try:
        payload = jwt_service.verify_token(credentials.credentials, token_type="access")
    except HTTPException:
        return None
    
    user_id = payload.get("user_id")
    if not user_id:
        return None
    
    user_service = get_user_service()
    user = user_service.get_user_by_id(db, user_id)
    
    return user if user and user.is_active else None
