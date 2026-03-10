"""
Database models and connection management.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import String, Float, DateTime, Integer, ForeignKey, Boolean

from cogniflow.config import settings


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# Enums

class SignalType(str, Enum):
    """Types of market signals."""
    PRICE_ANOMALY = "PRICE_ANOMALY"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    VOLATILITY_CHANGE = "VOLATILITY_CHANGE"
    MA_CROSS = "MA_CROSS"
    SUPPORT_RESISTANCE_TOUCH = "SUPPORT_RESISTANCE_TOUCH"


class SignalSeverity(str, Enum):
    """Severity levels for signals."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IntentType(str, Enum):
    """Types of user intents."""
    BUY_DIP = "BUY_DIP"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_PROFIT_LOSS = "STOP_PROFIT_LOSS"
    REBALANCE = "REBALANCE"
    REDUCE_RISK = "REDUCE_RISK"
    HOLD_WAIT = "HOLD_WAIT"
    INFO_SEEKING = "INFO_SEEKING"
    ADD_POSITION = "ADD_POSITION"
    DIVERSIFY = "DIVERSIFY"
    REVIEW_STOPS = "REVIEW_STOPS"


class IntentStatus(str, Enum):
    """Status of user intents."""
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class MemoryTier(str, Enum):
    """Memory hierarchy tiers."""
    WORKING = "WORKING"           # ~4K tokens, ~4 hours
    SHORT_TERM = "SHORT_TERM"     # ~16K tokens, ~7 days
    LONG_TERM = "LONG_TERM"       # ~64K tokens, ~1 year


class ContextType(str, Enum):
    """Types of context entries."""
    MARKET_PATTERN = "MARKET_PATTERN"
    SIGNAL_HISTORY = "SIGNAL_HISTORY"
    INTENT_HISTORY = "INTENT_HISTORY"
    USER_BEHAVIOR = "USER_BEHAVIOR"
    PORTFOLIO_STATE = "PORTFOLIO_STATE"
    CONVERSATION = "CONVERSATION"
    EXTERNAL_NEWS = "EXTERNAL_NEWS"


# Database Engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Models

class MarketSignal(Base):
    """Market signal entity."""
    
    __tablename__ = "market_signals"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    signal_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    
    price_at_signal: Mapped[float] = mapped_column(Float)
    price_reference: Mapped[Optional[float]] = mapped_column(nullable=True)
    volume_at_signal: Mapped[Optional[float]] = mapped_column(nullable=True)
    
    indicators_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


class UserIntent(Base):
    """User intent entity."""
    
    __tablename__ = "user_intents"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    
    intent_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    
    confidence: Mapped[float] = mapped_column(Float)
    urgency: Mapped[float] = mapped_column(Float)
    priority_score: Mapped[float] = mapped_column(Float)
    
    trigger_signal_ids: Mapped[list] = mapped_column(JSONB, default=list)
    target_symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    proposed_action: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    evaluation_scores: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    evaluation_reasoning: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base):
    """User entity."""
    
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    
    risk_profile: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    trading_experience: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    preferred_holdings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketSnapshot(Base):
    """Market snapshot entity."""
    
    __tablename__ = "market_snapshots"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    
    price: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    
    ma_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ma_50: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    additional_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class MemoryEntry(Base):
    """Memory entry entity for context management."""
    
    __tablename__ = "memory_entries"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    
    tier: Mapped[str] = mapped_column(String(20))
    context_type: Mapped[str] = mapped_column(String(50))
    
    content: Mapped[str] = mapped_column(String(10000))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    
    is_folded: Mapped[bool] = mapped_column(Boolean, default=False)
    folded_from_entries: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserProfile(Base):
    """User profile entity for personalization."""
    
    __tablename__ = "user_profiles"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    
    # Preferences
    preferred_intent_types: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    disliked_intent_types: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    preferred_symbols: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    
    # Communication
    notification_frequency: Mapped[str] = mapped_column(String(20), default="immediate")
    preferred_contact_method: Mapped[str] = mapped_column(String(20), default="app")
    quiet_hours_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quiet_hours_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Behavioral
    average_response_time_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    acceptance_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
