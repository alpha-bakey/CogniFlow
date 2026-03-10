"""
Context Management Module - Main module coordinator.
"""
import logging
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from cogniflow.config import settings
from cogniflow.core.redis_queue import RedisMessageQueue
from cogniflow.core.context.memory_manager import HierarchicalMemoryManager
from cogniflow.core.context.user_profiler import UserProfiler
from cogniflow.models.database import MemoryTier, ContextType

logger = logging.getLogger(__name__)


class ContextManagementModule:
    """
    Context Management Module - Hierarchical memory and user profiling.
    
    This module:
    1. Manages hierarchical memory (Working/Short-term/Long-term)
    2. Implements Context-Folding for token efficiency
    3. Learns user preferences from behavior
    4. Provides relevant context for intent generation
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        memory_manager: Optional[HierarchicalMemoryManager] = None,
        user_profiler: Optional[UserProfiler] = None,
        redis_url: Optional[str] = None,
    ):
        self.db = db_session
        self.memory = memory_manager or HierarchicalMemoryManager(db_session)
        self.profiler = user_profiler or UserProfiler(db_session)
        self._running = False
        
        # Initialize Redis queue
        self._redis = RedisMessageQueue(redis_url or settings.redis_url)
    
    async def initialize(self):
        """Initialize Redis connection."""
        try:
            await self._redis.connect()
            await self._redis.on_user_intent(self._handle_user_intent)
            logger.info("ContextManagementModule initialized")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Continuing without Redis.")
            self._redis = None
    
    async def shutdown(self):
        """Cleanup resources."""
        self._running = False
        if self._redis:
            await self._redis.disconnect()
    
    async def start(self):
        """Start consuming messages from Redis."""
        if self._running:
            return
        
        self._running = True
        
        if self._redis:
            logger.info("ContextManagementModule started - consuming user intents")
            await self._redis.start_consuming()
    
    async def _handle_user_intent(self, intent_data: Dict[str, Any]):
        """Handle user intent from Redis."""
        try:
            user_id = intent_data.get("user_id")
            intent_id = intent_data.get("intent_id")
            intent_type = intent_data.get("intent_type")
            symbol = intent_data.get("symbol")
            
            # Store in memory
            content = f"Intent generated: {intent_type} for {symbol}"
            
            await self.memory.add_entry(
                user_id=user_id or 0,
                tier=MemoryTier.WORKING,
                context_type=ContextType.INTENT_HISTORY,
                content=content,
                importance=0.7,
            )
            
            logger.debug(f"Recorded intent {intent_id} to memory")
            
        except Exception as e:
            logger.error(f"Error handling user intent: {e}")
    
    async def record_signal(
        self,
        user_id: int,
        signal_type: str,
        symbol: str,
        description: str,
    ):
        """Record a market signal to memory."""
        content = f"Market signal: {signal_type} for {symbol} - {description}"
        
        await self.memory.add_entry(
            user_id=user_id,
            tier=MemoryTier.WORKING,
            context_type=ContextType.MARKET_PATTERN,
            content=content,
            importance=0.6,
        )
    
    async def record_decision(
        self,
        user_id: int,
        intent_id: int,
        decision: str,  # 'accepted', 'rejected', 'executed'
        notes: Optional[str] = None,
    ):
        """Record a user decision to memory."""
        content = f"Decision: {decision} for intent {intent_id}"
        if notes:
            content += f" - {notes}"
        
        await self.memory.add_entry(
            user_id=user_id,
            tier=MemoryTier.WORKING,
            context_type=ContextType.USER_BEHAVIOR,
            content=content,
            importance=0.8,
        )
        
        # Also update profile
        response_time = None  # Could be calculated from intent creation time
        await self.profiler.record_intent_interaction(
            user_id=user_id,
            intent_id=intent_id,
            action=decision,
            response_time_minutes=response_time,
        )
    
    async def get_context_for_query(
        self,
        user_id: int,
        query: str,
        max_tokens: int = 4000,
    ) -> str:
        """
        Get relevant context for a query.
        
        Args:
            user_id: User ID
            query: Query string
            max_tokens: Maximum tokens to return
            
        Returns:
            Relevant context
        """
        return await self.memory.query_relevant(user_id, query, max_tokens)
    
    async def get_user_context(
        self,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        Get complete user context for intent evaluation.
        
        Returns:
            User context dictionary
        """
        # Get profile summary
        profile = await self.profiler.get_profile_summary(user_id)
        
        # Get recent memory
        recent_memory = await self.memory.get_entries(
            user_id=user_id,
            tier=MemoryTier.WORKING,
            limit=10,
        )
        
        # Get memory stats
        memory_stats = await self.memory.get_stats(user_id)
        
        return {
            "profile": profile,
            "recent_memory": [
                {
                    "type": e.context_type,
                    "content": e.content[:200],
                    "importance": e.importance_score,
                }
                for e in recent_memory
            ],
            "memory_stats": memory_stats,
        }
    
    async def cleanup(self, user_id: int) -> int:
        """
        Cleanup expired entries for a user.
        
        Returns:
            Number of entries cleaned up
        """
        return await self.memory.cleanup_expired(user_id)
