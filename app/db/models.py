"""
Supabase Database Models - SQLAlchemy ORM
Defines all database tables for ROSE backend
"""
from sqlalchemy import Column, String, Integer, DateTime, Enum as SQLEnum, Boolean, Float, Text, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()


class UserTier(str, enum.Enum):
    """Freemium tier levels"""
    FREE = "free"
    PLUS = "plus"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    ADMIN = "admin"


class User(Base):
    """User account and subscription information"""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True)  # UUID
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    tier = Column(SQLEnum(UserTier), default=UserTier.FREE, index=True)
    monthly_token_limit = Column(Integer, default=10000)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    usage_records = relationship("UsageRecord", back_populates="user")
    billing_events = relationship("BillingEvent", back_populates="user")
    
    def __repr__(self):
        return f"<User {self.email} ({self.tier})>"


class UsageRecord(Base):
    """Token usage tracking per request"""
    __tablename__ = "usage_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    endpoint = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    total_billable_tokens = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    cache_hit = Column(Boolean, default=False)
    error = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    
    # Relationship
    user = relationship("User", back_populates="usage_records")
    
    def __repr__(self):
        return f"<UsageRecord {self.user_id} {self.total_billable_tokens} tokens>"


class BillingEvent(Base):
    """Payment and subscription history"""
    __tablename__ = "billing_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)  # "upgrade", "downgrade", "payment", "refund", "cancellation"
    old_tier = Column(SQLEnum(UserTier), nullable=True)
    new_tier = Column(SQLEnum(UserTier), nullable=True)
    amount = Column(Float, nullable=True)  # In USD
    currency = Column(String, default="USD")
    stripe_event_id = Column(String, nullable=True, unique=True)
    status = Column(String, default="completed")  # "pending", "completed", "failed"
    event_metadata = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationship
    user = relationship("User", back_populates="billing_events")
    
    def __repr__(self):
        return f"<BillingEvent {self.user_id} {self.event_type}>"


class MonthlyUsage(Base):
    """Aggregated monthly usage for billing"""
    __tablename__ = "monthly_usage"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    total_tokens = Column(Integer, default=0)
    total_requests = Column(Integer, default=0)
    unique_sessions = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'year', 'month', name='uq_user_year_month'),
    )
    
    def __repr__(self):
        return f"<MonthlyUsage {self.user_id} {self.year}-{self.month:02d}>"
