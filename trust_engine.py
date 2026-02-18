"""
AI Governor Bot - Trust Score Engine
Behavioral intelligence and reputation system
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import asyncio

from settings import get_settings


@dataclass
class TrustUpdate:
    """Trust score update result."""
    new_score: float
    old_score: float
    change: float
    reason: str
    restrictions_applied: list


class TrustEngine:
    """
    Advanced trust score management system.
    Calculates and updates user trust scores based on behavior.
    """
    
    def __init__(self):
        self.settings = get_settings()
        
    async def calculate_trust_update(
        self,
        user_id: int,
        group_id: int,
        action_type: str,  # 'positive_interaction', 'violation', 'mute', 'ban_attempt'
        severity: str = "low",  # low, medium, high, critical
        db_session=None,
    ) -> TrustUpdate:
        """
        Calculate trust score update based on user action.
        
        Formula:
        T_new = T_old + (positive × 0.8) - (violations × 5) - (mute × 8) - (ban × 15)
        """
        # Get current trust score from database
        current_trust = await self._get_current_trust(user_id, group_id, db_session)
        old_score = current_trust
        
        change = 0.0
        reason = ""
        
        # Calculate change based on action type
        if action_type == "positive_interaction":
            change = self.settings.TRUST_BONUS_POSITIVE
            reason = "Positive interaction"
            
        elif action_type == "violation":
            multiplier = {"low": 1, "medium": 2, "high": 3, "critical": 5}
            change = -self.settings.TRUST_PENALTY_VIOLATION * multiplier.get(severity, 1)
            reason = f"Violation ({severity})"
            
        elif action_type == "mute":
            change = -self.settings.TRUST_PENALTY_MUTE
            reason = "User muted"
            
        elif action_type == "ban_attempt":
            change = -self.settings.TRUST_PENALTY_BAN
            reason = "Ban attempt"
        
        # Calculate new score
        new_score = max(
            self.settings.TRUST_MIN,
            min(self.settings.TRUST_MAX, current_trust + change)
        )
        
        # Determine restrictions
        restrictions = self._determine_restrictions(new_score)
        
        return TrustUpdate(
            new_score=round(new_score, 2),
            old_score=round(old_score, 2),
            change=round(change, 2),
            reason=reason,
            restrictions_applied=restrictions,
        )
    
    async def _get_current_trust(
        self, 
        user_id: int, 
        group_id: int,
        db_session
    ) -> float:
        """Get current trust score from database."""
        if not db_session:
            return self.settings.TRUST_INITIAL
        
        try:
            from database import GroupUser
            result = await db_session.execute(
                select(GroupUser).where(
                    GroupUser.user_id == user_id,
                    GroupUser.group_id == group_id
                )
            )
            membership = result.scalar_one_or_none()
            
            if membership:
                return membership.trust_score
        except Exception:
            pass
        
        return self.settings.TRUST_INITIAL
    
    def _determine_restrictions(self, trust_score: float) -> List[str]:
        """Determine restrictions based on trust score."""
        restrictions = []
        
        if trust_score < self.settings.TRUST_AUTO_RESTRICT_MEDIA:
            restrictions.append("media_restricted")
        
        if trust_score < self.settings.TRUST_AUTO_BAN:
            restrictions.append("auto_ban_candidate")
        
        return restrictions
    
    async def update_user_trust(
        self,
        user_id: int,
        group_id: int,
        new_score: float,
        db_session
    ):
        """Update user trust score in database."""
        if not db_session:
            return
        
        try:
            from database import GroupUser
            from sqlalchemy import update
            
            await db_session.execute(
                update(GroupUser)
                .where(
                    GroupUser.user_id == user_id,
                    GroupUser.group_id == group_id
                )
                .values(trust_score=new_score)
            )
            await db_session.commit()
        except Exception as e:
            await db_session.rollback()
            raise e
    
    def calculate_trust_decay(
        self, 
        current_score: float,
        days_inactive: int
    ) -> float:
        """Calculate trust score decay for inactive users."""
        if days_inactive < 7:
            return current_score
        
        # Decay formula: lose 2 points per week of inactivity after first week
        decay = ((days_inactive - 7) // 7) * 2
        return max(self.settings.TRUST_MIN, current_score - decay)


# Global trust engine instance
trust_engine = TrustEngine()
