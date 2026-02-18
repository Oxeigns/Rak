"""
AI Governor Bot - Anti-Raid Protection System
Advanced raid detection and prevention
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
import re

from settings import get_settings


@dataclass
class RaidDetectionResult:
    """Raid detection result."""
    is_raid: bool
    raid_type: str
    confidence: float
    affected_users: List[int]
    recommended_action: str
    trigger_reason: str


@dataclass
class JoinEvent:
    """User join event."""
    user_id: int
    username: str
    account_created_at: Optional[datetime]
    joined_at: datetime = field(default_factory=datetime.utcnow)


class AntiRaidSystem:
    """
    Advanced anti-raid protection system.
    Detects mass joins, new account patterns, and username similarities.
    """
    
    def __init__(self):
        self.settings = get_settings()
        # In-memory join tracking (use Redis in production)
        self.join_history: Dict[int, List[JoinEvent]] = defaultdict(list)
        self.raid_status: Dict[int, Dict] = {}
        self.raid_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._state_lock = asyncio.Lock()
        
    async def record_join(
        self,
        group_id: int,
        user_id: int,
        username: str,
        account_created_at: Optional[datetime]
    ):
        """Record a user join event."""
        event = JoinEvent(
            user_id=user_id,
            username=username,
            account_created_at=account_created_at,
        )
        
        async with self._state_lock:
            # Add to history
            self.join_history[group_id].append(event)

            # Clean old events (> 5 minutes)
            cutoff = datetime.utcnow() - timedelta(minutes=5)
            self.join_history[group_id] = [
                e for e in self.join_history[group_id] if e.joined_at > cutoff
            ]
            # Keep memory bounded per group
            self.join_history[group_id] = self.join_history[group_id][-500:]

        # Check for raid
        raid_result = await self.detect_raid(group_id)

        async with self._state_lock:
            if raid_result.is_raid and group_id not in self.raid_status:
                await self.activate_raid_protection(group_id, raid_result)
        
        return raid_result
    
    async def detect_raid(self, group_id: int) -> RaidDetectionResult:
        """
        Detect if a raid is in progress.
        
        Trigger conditions:
        - > 10 joins in 30 seconds
        - > 5 new accounts (< 7 days old)
        - Similar username patterns
        """
        async with self._state_lock:
            events = list(self.join_history[group_id])
        
        if len(events) < 3:
            return RaidDetectionResult(
                is_raid=False,
                raid_type="none",
                confidence=0.0,
                affected_users=[],
                recommended_action="none",
                trigger_reason="Insufficient data",
            )
        
        # Check 1: Mass join velocity
        recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
        recent_joins = [e for e in events if e.joined_at > recent_cutoff]
        
        if len(recent_joins) >= self.settings.RAID_JOIN_THRESHOLD:
            return RaidDetectionResult(
                is_raid=True,
                raid_type="mass_join",
                confidence=min(len(recent_joins) / 20, 1.0),
                affected_users=[e.user_id for e in recent_joins],
                recommended_action="enable_slow_mode_restrict_new",
                trigger_reason=f"{len(recent_joins)} joins in 30 seconds",
            )
        
        # Check 2: New account pattern
        new_account_threshold = datetime.utcnow() - timedelta(
            days=self.settings.RAID_NEW_ACCOUNT_DAYS
        )
        new_accounts = [
            e for e in events 
            if e.account_created_at and e.account_created_at > new_account_threshold
        ]
        
        if len(new_accounts) >= 5:
            return RaidDetectionResult(
                is_raid=True,
                raid_type="new_account_wave",
                confidence=min(len(new_accounts) / 10, 1.0),
                affected_users=[e.user_id for e in new_accounts],
                recommended_action="restrict_new_accounts_verify",
                trigger_reason=f"{len(new_accounts)} new accounts joined",
            )
        
        # Check 3: Username pattern similarity
        pattern_score = self._analyze_username_patterns(events)
        if pattern_score > 0.7:
            similar_users = self._get_similar_username_users(events)
            return RaidDetectionResult(
                is_raid=True,
                raid_type="username_pattern",
                confidence=pattern_score,
                affected_users=similar_users,
                recommended_action="manual_review_ban_pattern",
                trigger_reason="Suspicious username patterns detected",
            )
        
        return RaidDetectionResult(
            is_raid=False,
            raid_type="none",
            confidence=0.0,
            affected_users=[],
            recommended_action="monitor",
            trigger_reason="No raid patterns detected",
        )
    
    def _analyze_username_patterns(self, events: List[JoinEvent]) -> float:
        """Analyze username patterns for bot/raid indicators."""
        if len(events) < 5:
            return 0.0
        
        usernames = [e.username for e in events if e.username]
        if len(usernames) < 5:
            return 0.0
        
        # Check for:
        # 1. Sequential numbers (user1, user2, user3)
        # 2. Random character patterns
        # 3. Same prefix/suffix
        
        patterns = {
            "sequential": 0,
            "random_chars": 0,
            "same_prefix": 0,
            "same_suffix": 0,
        }
        
        # Extract numbers from usernames
        numbers = []
        prefixes = defaultdict(int)
        suffixes = defaultdict(int)
        
        for username in usernames:
            # Check for numbers
            nums = re.findall(r'\d+', username)
            if nums:
                numbers.extend([int(n) for n in nums])
            
            # Check for random character strings (8+ chars, mixed case+numbers)
            if len(username) >= 8 and re.match(r'^[a-zA-Z0-9]+$', username):
                patterns["random_chars"] += 1
            
            # Extract prefix (first 4 chars)
            if len(username) >= 4:
                prefixes[username[:4].lower()] += 1
            
            # Extract suffix (last 4 chars)
            if len(username) >= 4:
                suffixes[username[-4:].lower()] += 1
        
        # Check for sequential numbers
        if len(numbers) >= 3:
            sorted_nums = sorted(numbers)
            sequential = sum(
                1 for i in range(len(sorted_nums) - 1) 
                if sorted_nums[i+1] - sorted_nums[i] == 1
            )
            if sequential >= 2:
                patterns["sequential"] = sequential
        
        # Check for common prefixes/suffixes
        max_prefix = max(prefixes.values()) if prefixes else 0
        max_suffix = max(suffixes.values()) if suffixes else 0
        
        if max_prefix >= 3:
            patterns["same_prefix"] = max_prefix
        if max_suffix >= 3:
            patterns["same_suffix"] = max_suffix
        
        # Calculate overall pattern score
        score = 0.0
        score += min(patterns["sequential"] / 5, 0.3)
        score += min(patterns["random_chars"] / 10, 0.3)
        score += min(patterns["same_prefix"] / 5, 0.2)
        score += min(patterns["same_suffix"] / 5, 0.2)
        
        return min(score, 1.0)
    
    def _get_similar_username_users(self, events: List[JoinEvent]) -> List[int]:
        """Get user IDs with similar username patterns."""
        # Simple implementation - return recent users if pattern detected
        recent = sorted(events, key=lambda x: x.joined_at, reverse=True)[:10]
        return [e.user_id for e in recent]
    
    async def activate_raid_protection(
        self,
        group_id: int,
        raid_result: RaidDetectionResult
    ):
        """Activate raid protection measures."""
        async with self.raid_locks[group_id]:
            self.raid_status[group_id] = {
                "active": True,
                "started_at": datetime.utcnow(),
                "raid_type": raid_result.raid_type,
                "affected_users": raid_result.affected_users,
                "measures": [],
            }
    
    async def deactivate_raid_protection(self, group_id: int):
        """Deactivate raid protection."""
        async with self.raid_locks[group_id]:
            if group_id in self.raid_status:
                self.raid_status[group_id]["active"] = False
                self.raid_status[group_id]["ended_at"] = datetime.utcnow()
    
    async def is_raid_active(self, group_id: int) -> bool:
        """Check if raid protection is currently active."""
        async with self._state_lock:
            status = self.raid_status.get(group_id)
            return status.get("active", False) if status else False


# Global anti-raid system instance
anti_raid_system = AntiRaidSystem()
