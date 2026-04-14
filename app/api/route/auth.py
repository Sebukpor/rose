"""
Authentication Endpoints
Handles user registration, login, and token refresh
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.db.database import get_db
from app.db.models import User
from app.services.user_service import get_user_service
from app.services.auth_service import get_jwt_service
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """User registration request"""
    email: EmailStr
    password: str
    tier: str = "free"  # free, plus, pro, enterprise


class RegisterResponse(BaseModel):
    """Registration response with tokens"""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user_id: str
    email: str
    tier: str


class LoginRequest(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Login response with tokens"""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user_id: str
    email: str
    tier: str


class RefreshRequest(BaseModel):
    """Token refresh request"""
    refresh_token: str


class TokenResponse(BaseModel):
    """Token response"""
    access_token: str
    token_type: str
    expires_in: int


class UserProfile(BaseModel):
    """User profile response"""
    user_id: str
    email: str
    tier: str
    monthly_token_limit: int
    is_active: bool
    created_at: str


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register new user account.
    
    Args:
        request: Registration data (email, password, tier)
        db: Database session
    
    Returns:
        Access token, refresh token, and user info
    
    Raises:
        HTTPException: 400 if email already exists or invalid tier
    """
    user_service = get_user_service()
    
    try:
        user = user_service.create_user(
            db=db,
            email=request.email,
            password=request.password,
            tier=request.tier
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    tokens = user_service.create_tokens(user)
    
    return RegisterResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
        user_id=user.id,
        email=user.email,
        tier=user.tier.value
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return tokens.
    
    Args:
        request: Login credentials (email, password)
        db: Database session
    
    Returns:
        Access token, refresh token, and user info
    
    Raises:
        HTTPException: 401 if credentials invalid
    """
    user_service = get_user_service()
    
    user = user_service.authenticate_user(
        db=db,
        email=request.email,
        password=request.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    tokens = user_service.create_tokens(user)
    
    return LoginResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
        user_id=user.id,
        email=user.email,
        tier=user.tier.value
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshRequest,
    db: Session = Depends(get_db)
):
    """
    Exchange refresh token for new access token.
    
    Args:
        request: Refresh token
        db: Database session
    
    Returns:
        New access token
    
    Raises:
        HTTPException: 401 if refresh token invalid
    """
    jwt_service = get_jwt_service()
    
    try:
        payload = jwt_service.verify_token(request.refresh_token, token_type="refresh")
    except HTTPException as e:
        raise e
    
    user_id = payload.get("user_id")
    user_service = get_user_service()
    user = user_service.get_user_by_id(db, user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    access_token = jwt_service.create_access_token(
        user_id=user.id,
        email=user.email,
        tier=user.tier.value
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=jwt_service.expiration_days * 86400
    )


@router.get("/me", response_model=UserProfile)
async def get_profile(
    current_user: User = Depends(get_current_user)
):
    """
    Get current user profile.
    
    Args:
        current_user: Current authenticated user
    
    Returns:
        User profile information
    """
    return UserProfile(
        user_id=current_user.id,
        email=current_user.email,
        tier=current_user.tier.value,
        monthly_token_limit=current_user.monthly_token_limit,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat()
    )
