"""
User Profiler - Learns user preferences from behavior.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from sqlalchemy.dialects.postgresql import insert

from cogniflow.models.database import UserProfile, UserIntent, IntentStatus

logger = logging.getLogger(__name__)


class UserProfiler:
    """
    Learns user preferences and behavior patterns from interaction history.
    
    Tracks:
    - Preferred intent types
    - Preferred symbols
    - Response patterns
    - Risk tolerance evolution
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def get_or_create_profile(self, user_id: int) -> UserProfile:
        """Get existing profile or create new one."""
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()
        
        if not profile:
            profile = UserProfile(user_id=user_id)
            self.db.add(profile)
            await self.db.commit()
            await self.db.refresh(profile)
            logger.info(f"Created new profile for user {user_id}")
        
        return profile
    
    async def record_intent_interaction(
        self,
        user_id: int,
        intent_id: int,
        action: str,  # 'accepted', 'rejected', 'ignored'
        response_time_minutes: Optional[float] = None,
    ):
        """
        Record user interaction with an intent.
        
        Args:
            user_id: User ID
            intent_id: Intent ID
            action: User action (accepted/rejected/ignored)
            response_time_minutes: Time to respond
        """
        profile = await self.get_or_create_profile(user_id)
        
        # Fetch intent details
        stmt = select(UserIntent).where(UserIntent.id == intent_id)
        result = await self.db.execute(stmt)
        intent = result.scalar_one_or_none()
        
        if not intent:
            return
        
        # Update intent status
        if action == "accepted":
            intent.status = IntentStatus.ACCEPTED.value
            intent.accepted_at = datetime.now(timezone.utc)
        elif action == "rejected":
            intent.status = IntentStatus.REJECTED.value
            intent.rejected_at = datetime.now(timezone.utc)
        
        # Update profile statistics
        await self._update_stats(profile, intent, action, response_time_minutes)
        
        await self.db.commit()
        logger.debug(f"Recorded {action} for intent {intent_id}")
    
    async def _update_stats(
        self,
        profile: UserProfile,
        intent: UserIntent,
        action: str,
        response_time: Optional[float],
    ):
        """Update profile statistics based on interaction."""
        # Track preferred intent types
        if action == "accepted":
            preferred = list(profile.preferred_intent_types or [])
            if intent.intent_type not in preferred:
                preferred.append(intent.intent_type)
                profile.preferred_intent_types = preferred[:10]  # Keep top 10
        elif action == "rejected":
            disliked = list(profile.disliked_intent_types or [])
            if intent.intent_type not in disliked:
                disliked.append(intent.intent_type)
                profile.disliked_intent_types = disliked[:10]
        
        # Track preferred symbols
        if action == "accepted":
            symbols = list(profile.preferred_symbols or [])
            if intent.target_symbol and intent.target_symbol not in symbols:
                symbols.append(intent.target_symbol)
                profile.preferred_symbols = symbols[:20]  # Keep top 20
        
        # Update response time average
        if response_time is not None:
            current_avg = profile.average_response_time_minutes or response_time
            # Simple exponential moving average
            profile.average_response_time_minutes = current_avg * 0.9 + response_time * 0.1
        
        # Update acceptance rate
        await self._recalculate_acceptance_rate(profile)
    
    async def _recalculate_acceptance_rate(self, profile: UserProfile):
        """Recalculate acceptance rate from recent history."""
        stmt = select(
            func.count().filter(UserIntent.status == IntentStatus.ACCEPTED.value),
            func.count(),
        ).where(
            UserIntent.user_id == profile.user_id,
        )
        
        result = await self.db.execute(stmt)
        accepted, total = result.first()
        
        if total > 0:
            profile.acceptance_rate = accepted / total
    
    async def analyze_preferences(self, user_id: int) -> Dict[str, Any]:
        """
        Analyze user preferences from interaction history.
        
        Returns:
            Dictionary of inferred preferences
        """
        profile = await self.get_or_create_profile(user_id)
        
        # Analyze intent preferences
        stmt = select(
            UserIntent.intent_type,
            func.count().filter(UserIntent.status == IntentStatus.ACCEPTED.value),
            func.count(),
        ).where(
            UserIntent.user_id == user_id,
        ).group_by(UserIntent.intent_type)
        
        result = await self.db.execute(stmt)
        intent_stats = result.all()
        
        # Calculate acceptance rates by intent type
        intent_preferences = {}
        for intent_type, accepted, total in intent_stats:
            if total > 0:
                intent_preferences[intent_type] = {
                    "acceptance_rate": accepted / total,
                    "total": total,
                }
        
        # Symbol preferences
        symbol_stmt = select(
            UserIntent.target_symbol,
            func.count().filter(UserIntent.status == IntentStatus.ACCEPTED.value),
            func.count(),
        ).where(
            UserIntent.user_id == user_id,
        ).group_by(UserIntent.target_symbol)
        
        result = await self.db.execute(symbol_stmt)
        symbol_stats = result.all()
        
        symbol_preferences = {
            row[0]: {"acceptance_rate": row[1] / row[2], "total": row[2]}
            for row in symbol_stats if row[2] > 0 and row[0]
        }
        
        # Time-of-day patterns
        hour_stmt = select(
            func.extract('hour', UserIntent.created_at),
            func.count(),
        ).where(
            UserIntent.user_id == user_id,
        ).group_by(func.extract('hour', UserIntent.created_at))
        
        result = await self.db.execute(hour_stmt)
        hour_distribution = {int(row[0]): row[1] for row in result.all()}
        
        # Infer quiet hours (low activity periods)
        all_hours = set(range(24))
        active_hours = set(hour_distribution.keys())
        quiet_hours = list(all_hours - active_hours)[:8]  # Up to 8 quiet hours
        
        return {
            "preferred_intents": intent_preferences,
            "preferred_symbols": symbol_preferences,
            "hour_distribution": hour_distribution,
            "suggested_quiet_hours": quiet_hours if len(quiet_hours) >= 4 else None,
            "overall_acceptance_rate": profile.acceptance_rate,
            "avg_response_time_minutes": profile.average_response_time_minutes,
            "notification_frequency": self._infer_notification_frequency(profile),
        }
    
    def _infer_notification_frequency(self, profile: UserProfile) -> str:
        """Infer preferred notification frequency from behavior."""
        if not profile.average_response_time_minutes:
            return "immediate"
        
        avg_minutes = profile.average_response_time_minutes
        
        if avg_minutes < 30:
            return "immediate"
        elif avg_minutes < 120:
            return "batched_hourly"
        elif avg_minutes < 480:
            return "batched_4h"
        else:
            return "daily_digest"
    
    async def get_profile_summary(self, user_id: int) -> Dict[str, Any]:
        """Get a summary of user profile."""
        profile = await self.get_or_create_profile(user_id)
        
        return {
            "user_id": user_id,
            "risk_profile": profile.risk_profile,
            "preferred_intent_types": profile.preferred_intent_types,
            "preferred_symbols": profile.preferred_symbols,
            "notification_frequency": profile.notification_frequency,
            "preferred_contact": profile.preferred_contact_method,
            "quiet_hours": {
                "start": profile.quiet_hours_start,
                "end": profile.quiet_hours_end,
            } if profile.quiet_hours_start else None,
            "behavioral_stats": {
                "acceptance_rate": profile.acceptance_rate,
                "avg_response_time_minutes": profile.average_response_time_minutes,
            },
        }
    
    async def update_preferences(
        self,
        user_id: int,
        preferences: Dict[str, Any],
    ):
        """
        Update user preferences (explicit user input).
        
        Args:
            user_id: User ID
            preferences: Dictionary of preference updates
        """
        profile = await self.get_or_create_profile(user_id)
        
        if "risk_profile" in preferences:
            profile.risk_profile = preferences["risk_profile"]
        
        if "notification_frequency" in preferences:
            profile.notification_frequency = preferences["notification_frequency"]
        
        if "preferred_contact_method" in preferences:
            profile.preferred_contact_method = preferences["preferred_contact_method"]
        
        if "quiet_hours_start" in preferences:
            profile.quiet_hours_start = preferences["quiet_hours_start"]
        
        if "quiet_hours_end" in preferences:
            profile.quiet_hours_end = preferences["quiet_hours_end"]
        
        if "preferred_symbols" in preferences:
            profile.preferred_symbols = preferences["preferred_symbols"]
        
        await self.db.commit()
        logger.info(f"Updated preferences for user {user_id}")
