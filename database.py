"""
AI Governor Bot - Database Models
Enterprise-grade PostgreSQL schema with SQLAlchemy
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum as PyEnum
import uuid

from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, Boolean, 
    DateTime, Text, ForeignKey, Enum, JSON, Index, 
    create_engine, UniqueConstraint, ARRAY, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session, validates
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import UUID, JSONB

from config.settings import get_settings

settings = get_settings()

Base = declarative_base()


# ==================== ENUMS ====================

class RiskLevel(PyEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def coerce(cls, value: "RiskLevel | str | None") -> "RiskLevel | None":
        """Normalize enum input safely from DB/Python/runtime payloads."""
        if value is None:
            return None
        if isinstance(value, cls):
            return value

        normalized = str(value).strip()
        if not normalized:
            return None

        try:
            return cls[normalized.upper()]
        except KeyError:
            return cls.LOW

    @property
    def normalized(self) -> str:
        """Lowercase representation for business logic and telemetry."""
        return self.name.lower()


RISK_LEVEL_ENUM = Enum(
    RiskLevel,
    name="risklevel",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
    validate_strings=True,
)

class ViolationType(PyEnum):
    SPAM = "spam"
    TOXICITY = "toxicity"
    SCAM = "scam"
    ILLEGAL = "illegal"
    PHISHING = "phishing"
    NSFW = "nsfw"
    FLOOD = "flood"
    RAID = "raid"
    ADVERTISING = "advertising"
    HATE_SPEECH = "hate_speech"
    MISINFORMATION = "misinformation"

class UserRole(PyEnum):
    MEMBER = "member"
    RESTRICTED = "restricted"
    ADMIN = "admin"
    OWNER = "owner"
    BANNED = "banned"

class PersonalityMode(PyEnum):
    FRIENDLY = "friendly"
    STRICT = "strict"
    CORPORATE = "corporate"
    FUNNY = "funny"
    OWNER = "owner"

class GroupType(PyEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


# ==================== MODELS ====================

class Group(Base):
    """Group/Chat configuration and metadata."""
    __tablename__ = "groups"
    
    id = Column(BigInteger, primary_key=True)
    title = Column(String(255), nullable=False)
    username = Column(String(100), nullable=True)
    group_type = Column(Enum(GroupType), default=GroupType.SUPERGROUP)
    is_active = Column(Boolean, default=True)
    
    # Configuration
    language = Column(String(10), default="en")
    personality_mode = Column(Enum(PersonalityMode), default=PersonalityMode.FRIENDLY)
    strict_mode = Column(Boolean, default=False)
    crypto_shield = Column(Boolean, default=False)
    deep_media_analysis = Column(Boolean, default=False)
    engagement_enabled = Column(Boolean, default=True)
    analytics_enabled = Column(Boolean, default=True)
    
    # Risk Thresholds (customizable per group)
    risk_threshold_critical = Column(Integer, default=85)
    risk_threshold_high = Column(Integer, default=70)
    risk_threshold_medium = Column(Integer, default=50)
    
    # Trust Score Settings
    auto_restrict_media_trust = Column(Integer, default=25)
    auto_ban_trust = Column(Integer, default=10)
    
    # Anti-Raid Settings
    raid_join_threshold = Column(Integer, default=10)
    raid_time_window = Column(Integer, default=30)
    raid_new_account_days = Column(Integer, default=7)
    
    # Engagement Settings
    daily_question_hour = Column(Integer, default=10)
    weekly_poll_day = Column(Integer, default=6)
    inactive_days_threshold = Column(Integer, default=7)
    
    # Metadata
    member_count = Column(Integer, default=0)
    message_count = Column(BigInteger, default=0)
    violation_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    settings = relationship("GroupSettings", back_populates="group", uselist=False)
    users = relationship("GroupUser", back_populates="group")
    violations = relationship("Violation", back_populates="group")
    messages = relationship("Message", back_populates="group")
    
    __table_args__ = (
        Index('idx_group_active', 'is_active'),
        Index('idx_group_type', 'group_type'),
    )


class GroupSettings(Base):
    """Extended group settings and custom rules."""
    __tablename__ = "group_settings"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), unique=True)
    
    # Custom Rules (JSON for flexibility)
    custom_banned_words = Column(JSONB, default=list)
    custom_allowed_links = Column(JSONB, default=list)
    custom_blocked_links = Column(JSONB, default=list)
    welcome_message = Column(Text, nullable=True)
    goodbye_message = Column(Text, nullable=True)
    
    # Feature Toggles
    welcome_new_members = Column(Boolean, default=True)
    captcha_enabled = Column(Boolean, default=False)
    delete_join_messages = Column(Boolean, default=True)
    delete_leave_messages = Column(Boolean, default=True)
    restrict_forwarding = Column(Boolean, default=False)
    restrict_channels = Column(Boolean, default=False)
    
    # Advanced AI Settings
    ai_moderation_enabled = Column(Boolean, default=True)
    ai_context_window = Column(Integer, default=10)
    ai_personality_strength = Column(Float, default=0.7)

    # Dynamic key-value config for custom panel settings
    config = Column(JSONB, default=dict)
    
    group = relationship("Group", back_populates="settings")


class User(Base):
    """Global user data across all groups."""
    __tablename__ = "users"
    
    id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True, index=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    language_code = Column(String(10), default="en")
    is_bot = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)
    
    # Global Statistics
    total_messages = Column(BigInteger, default=0)
    total_violations = Column(Integer, default=0)
    groups_count = Column(Integer, default=0)
    
    # Account Age (for raid detection)
    account_created_at = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    
    # Reputation
    global_trust_score = Column(Float, default=50.0)
    is_globally_flagged = Column(Boolean, default=False)
    
    # Relationships
    group_memberships = relationship("GroupUser", back_populates="user")
    violations = relationship("Violation", back_populates="user")
    messages = relationship("Message", back_populates="user")
    
    __table_args__ = (
        Index('idx_user_username', 'username'),
        Index('idx_user_trust', 'global_trust_score'),
    )


class GroupUser(Base):
    """User membership in specific groups with group-local data."""
    __tablename__ = "group_users"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    
    # Group-local role
    role = Column(Enum(UserRole), default=UserRole.MEMBER)
    is_admin = Column(Boolean, default=False)
    
    # Group-local trust score
    trust_score = Column(Float, default=50.0)
    violation_count = Column(Integer, default=0)
    message_count = Column(BigInteger, default=0)
    
    # Restrictions
    is_muted = Column(Boolean, default=False)
    mute_until = Column(DateTime, nullable=True)
    can_send_media = Column(Boolean, default=True)
    can_send_links = Column(Boolean, default=True)
    
    # Join info
    joined_at = Column(DateTime, default=datetime.utcnow)
    invited_by = Column(BigInteger, nullable=True)
    
    # Activity
    last_message_at = Column(DateTime, nullable=True)
    last_violation_at = Column(DateTime, nullable=True)
    
    group = relationship("Group", back_populates="users")
    user = relationship("User", back_populates="group_memberships")
    
    __table_args__ = (
        UniqueConstraint('group_id', 'user_id', name='unique_group_user'),
        Index('idx_group_user_trust', 'group_id', 'trust_score'),
    )


class Message(Base):
    """Message history for context and analysis."""
    __tablename__ = "messages"
    
    id = Column(BigInteger, primary_key=True)
    message_id = Column(BigInteger, nullable=False)  # Telegram message ID
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    
    # Content
    text = Column(Text, nullable=True)
    text_normalized = Column(Text, nullable=True)
    message_type = Column(String(50), default="text")  # text, photo, video, etc.
    
    # Media info
    file_id = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    # Risk Analysis
    risk_score = Column(Float, nullable=True)
    risk_level = Column(RISK_LEVEL_ENUM, nullable=True)
    ai_analysis = Column(JSONB, default=dict)
    
    # Action taken
    action_taken = Column(String(50), nullable=True)  # deleted, warned, allowed
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(String(50), default="auto")  # auto, admin_username
    
    # Metadata
    is_edited = Column(Boolean, default=False)
    is_forwarded = Column(Boolean, default=False)
    forwarded_from = Column(BigInteger, nullable=True)
    reply_to_message_id = Column(BigInteger, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    group = relationship("Group", back_populates="messages")
    user = relationship("User", back_populates="messages")
    
    __table_args__ = (
        Index('idx_message_group_time', 'group_id', 'created_at'),
        Index('idx_message_user', 'user_id'),
        Index('idx_message_risk', 'risk_score'),
    )

    @validates("risk_level")
    def validate_risk_level(self, key, value):
        return RiskLevel.coerce(value)


class Violation(Base):
    """Violation records for user history and pattern analysis."""
    __tablename__ = "violations"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    message_id = Column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    
    violation_type = Column(Enum(ViolationType), nullable=False)
    severity = Column(RISK_LEVEL_ENUM, nullable=False)
    risk_score = Column(Float, nullable=False)
    
    # Evidence
    message_text = Column(Text, nullable=True)
    ai_analysis = Column(JSONB, default=dict)
    evidence_screenshot = Column(String(255), nullable=True)
    
    # Action taken
    action_taken = Column(String(50), nullable=False)  # warn, mute, ban, delete
    duration = Column(Integer, nullable=True)  # in minutes, for mute
    
    # Appeal system
    is_appealed = Column(Boolean, default=False)
    appeal_reason = Column(Text, nullable=True)
    appeal_decision = Column(String(20), nullable=True)
    appealed_at = Column(DateTime, nullable=True)
    
    # Admin review
    reviewed_by = Column(BigInteger, nullable=True)
    review_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    group = relationship("Group", back_populates="violations")
    user = relationship("User", back_populates="violations")
    
    __table_args__ = (
        Index('idx_violation_group_user', 'group_id', 'user_id'),
        Index('idx_violation_type', 'violation_type'),
        Index('idx_violation_time', 'created_at'),
    )

    @validates("severity")
    def validate_severity(self, key, value):
        return RiskLevel.coerce(value)


class RaidEvent(Base):
    """Track raid attempts and anti-raid activations."""
    __tablename__ = "raid_events"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    
    # Event details
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    
    # Trigger info
    trigger_type = Column(String(50), nullable=False)  # mass_join, new_accounts, pattern
    trigger_count = Column(Integer, nullable=False)
    
    # Affected users
    users_involved = Column(ARRAY(BigInteger), default=list)
    users_banned = Column(Integer, default=0)
    users_restricted = Column(Integer, default=0)
    
    # Actions taken
    slow_mode_enabled = Column(Boolean, default=False)
    join_restrictions = Column(Boolean, default=False)
    media_locked = Column(Boolean, default=False)
    
    # Resolution
    resolved_by = Column(BigInteger, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_raid_group', 'group_id'),
        Index('idx_raid_time', 'started_at'),
    )


class EngagementLog(Base):
    """Track engagement activities and interactions."""
    __tablename__ = "engagement_logs"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    
    activity_type = Column(String(50), nullable=False)  # daily_question, poll, spotlight, etc
    content = Column(JSONB, default=dict)
    
    # Participation
    participants_count = Column(Integer, default=0)
    responses = Column(JSONB, default=list)
    
    # Timing
    scheduled_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, default=datetime.utcnow)
    
    # Status
    status = Column(String(20), default="completed")  # scheduled, completed, cancelled
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_engagement_group', 'group_id'),
        Index('idx_engagement_type', 'activity_type'),
    )


class AIAnalysisCache(Base):
    """Cache AI analysis results to reduce API costs."""
    __tablename__ = "ai_analysis_cache"
    
    id = Column(Integer, primary_key=True)
    
    # Content hash for lookup
    content_hash = Column(String(64), unique=True, nullable=False, index=True)
    content_type = Column(String(20), nullable=False)  # text, image, link
    
    # Cached results
    analysis_result = Column(JSONB, nullable=False)
    risk_score = Column(Float, nullable=True)
    
    # Cache metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    hit_count = Column(Integer, default=0)
    
    __table_args__ = (
        Index('idx_cache_expiry', 'expires_at'),
    )


class SystemLog(Base):
    """System-wide logging for debugging and auditing."""
    __tablename__ = "system_logs"
    
    id = Column(BigInteger, primary_key=True)
    
    log_level = Column(String(20), nullable=False)
    component = Column(String(100), nullable=False)
    event_type = Column(String(100), nullable=False)
    
    message = Column(Text, nullable=False)
    details = Column(JSONB, default=dict)
    
    group_id = Column(BigInteger, nullable=True)
    user_id = Column(BigInteger, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_log_level', 'log_level'),
        Index('idx_log_component', 'component'),
        Index('idx_log_time', 'created_at'),
        Index('idx_log_group', 'group_id'),
    )


# ==================== DATABASE CONNECTION ====================

class DatabaseManager:
    """Async database connection manager with retries and pooling."""

    def __init__(self):
        self.engine = None
        self.async_session: Optional[async_sessionmaker[AsyncSession]] = None

    async def initialize(self):
        """Initialize database connection pool with exponential backoff."""
        if self.engine is not None:
            return

        settings = get_settings()
        db_url = self._build_async_database_url(settings.DATABASE_URL)

        self.engine = create_async_engine(
            db_url,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            future=True,
        )

        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        max_attempts = 5
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                return
            except Exception as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                delay = min(0.5 * (2 ** (attempt - 1)), 8)
                await asyncio.sleep(delay)

        await self.close()
        raise RuntimeError(f"Database initialization failed after {max_attempts} attempts: {last_error}")

    async def create_tables(self):
        """Create all database tables once a connection is available."""
        if self.engine is None:
            await self.initialize()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_enum_values(self, enum_name: str) -> list[str]:
        """Return enum labels from PostgreSQL in sort order."""
        if self.engine is None:
            await self.initialize()

        query = text(
            """
            SELECT enumlabel
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = :enum_name
            ORDER BY enumsortorder
            """
        )

        async with self.engine.connect() as conn:
            result = await conn.execute(query, {"enum_name": enum_name})
            return [row[0] for row in result.fetchall()]

    def get_session(self) -> AsyncSession:
        """Get database session."""
        if self.async_session is None:
            raise RuntimeError("DatabaseManager is not initialized")
        return self.async_session()

    async def close(self):
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
        self.engine = None
        self.async_session = None

    @staticmethod
    def _build_async_database_url(db_url: str) -> str:
        """Convert database URL to SQLAlchemy asyncpg URL."""
        if db_url.startswith("postgresql+asyncpg://"):
            return db_url
        if db_url.startswith("postgresql://"):
            return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if db_url.startswith("postgres://"):
            return db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        return db_url


# Global database manager instance
db_manager = DatabaseManager()
