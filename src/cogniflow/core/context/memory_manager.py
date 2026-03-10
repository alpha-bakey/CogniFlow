"""
Hierarchical Memory Manager - Context-Folding implementation.
"""
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc

from cogniflow.config import settings
from cogniflow.models.database import MemoryEntry, MemoryTier, ContextType

logger = logging.getLogger(__name__)


class TokenEstimator:
    """Simple token estimator for text content."""
    
    @staticmethod
    def estimate(text: str) -> int:
        """Estimate token count (rough approximation)."""
        # Rough estimate: 1 token ≈ 4 characters for English
        return len(text) // 4


class HierarchicalMemoryManager:
    """
    Hierarchical Memory Manager implementing Context-Folding.
    
    Memory Tiers:
    - WORKING: ~4K tokens, ~4 hours
    - SHORT_TERM: ~16K tokens, ~7 days  
    - LONG_TERM: ~64K tokens, ~1 year
    
    Context-Folding: When a tier approaches capacity, older/less
    important entries are summarized (folded) into a single entry.
    """
    
    # Token budgets per tier
    TIER_BUDGETS = {
        MemoryTier.WORKING: settings.working_memory_budget,
        MemoryTier.SHORT_TERM: settings.short_term_memory_budget,
        MemoryTier.LONG_TERM: settings.long_term_memory_budget,
    }
    
    # Expiry durations
    TIER_EXPIRIES = {
        MemoryTier.WORKING: timedelta(hours=4),
        MemoryTier.SHORT_TERM: timedelta(days=7),
        MemoryTier.LONG_TERM: timedelta(days=365),
    }
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._estimator = TokenEstimator()
    
    async def add_entry(
        self,
        user_id: int,
        tier: MemoryTier,
        context_type: ContextType,
        content: str,
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """
        Add an entry to memory.
        
        Args:
            user_id: User ID
            tier: Memory tier
            context_type: Type of context
            content: Content to store
            importance: Importance score (0-1)
            metadata: Additional metadata
            
        Returns:
            Created memory entry
        """
        token_count = self._estimator.estimate(content)
        
        # Check if we need to make space
        budget = self.TIER_BUDGETS[tier]
        current_usage = await self._get_tier_usage(user_id, tier)
        
        if current_usage + token_count > budget * 0.9:
            await self._make_space(user_id, tier, token_count)
        
        # Create entry
        entry = MemoryEntry(
            user_id=user_id,
            tier=tier.value,
            context_type=context_type.value,
            content=content,
            token_count=token_count,
            importance_score=importance,
            expires_at=datetime.now(timezone.utc) + self.TIER_EXPIRIES[tier],
        )
        
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        
        logger.debug(f"Added {tier.value} entry: {token_count} tokens")
        
        return entry
    
    async def get_entries(
        self,
        user_id: int,
        tier: Optional[MemoryTier] = None,
        context_type: Optional[ContextType] = None,
        limit: int = 100,
    ) -> List[MemoryEntry]:
        """
        Retrieve memory entries.
        
        Args:
            user_id: User ID
            tier: Optional tier filter
            context_type: Optional context type filter
            limit: Maximum entries to return
            
        Returns:
            List of memory entries
        """
        conditions = [MemoryEntry.user_id == user_id]
        
        if tier:
            conditions.append(MemoryEntry.tier == tier.value)
        if context_type:
            conditions.append(MemoryEntry.context_type == context_type.value)
        
        stmt = select(MemoryEntry).where(and_(*conditions))
        stmt = stmt.order_by(desc(MemoryEntry.importance_score), desc(MemoryEntry.created_at))
        stmt = stmt.limit(limit)
        
        result = await self.db.execute(stmt)
        entries = result.scalars().all()
        
        # Update last_accessed
        now = datetime.now(timezone.utc)
        for entry in entries:
            entry.last_accessed_at = now
        
        await self.db.commit()
        
        return list(entries)
    
    async def query_relevant(
        self,
        user_id: int,
        query: str,
        max_tokens: int = 4000,
    ) -> str:
        """
        Query relevant context from all tiers.
        
        Implements tiered retrieval:
        1. Always include WORKING memory
        2. Fill remaining with SHORT_TERM
        3. Add LONG_TERM if space permits
        
        Args:
            user_id: User ID
            query: Query string
            max_tokens: Maximum tokens to return
            
        Returns:
            Concatenated relevant context
        """
        all_content = []
        token_count = 0
        
        # Priority order
        tiers = [MemoryTier.WORKING, MemoryTier.SHORT_TERM, MemoryTier.LONG_TERM]
        
        for tier in tiers:
            entries = await self.get_entries(user_id, tier=tier, limit=50)
            
            for entry in entries:
                if token_count + entry.token_count > max_tokens:
                    break
                
                all_content.append(entry.content)
                token_count += entry.token_count
            
            if token_count >= max_tokens * 0.8:
                break
        
        return "\n\n".join(all_content)
    
    async def fold_entries(
        self,
        user_id: int,
        tier: MemoryTier,
        entry_ids: List[int],
    ) -> Optional[MemoryEntry]:
        """
        Fold multiple entries into a summary entry.
        
        Args:
            user_id: User ID
            tier: Target tier
            entry_ids: IDs of entries to fold
            
        Returns:
            New folded entry or None
        """
        if len(entry_ids) < 2:
            return None
        
        # Fetch entries to fold
        stmt = select(MemoryEntry).where(
            and_(
                MemoryEntry.id.in_(entry_ids),
                MemoryEntry.user_id == user_id,
            )
        )
        result = await self.db.execute(stmt)
        entries = result.scalars().all()
        
        if len(entries) < 2:
            return None
        
        # Generate summary
        summary = self._generate_summary(entries)
        
        # Mark original entries as folded
        for entry in entries:
            entry.is_folded = True
        
        # Create folded entry
        folded = await self.add_entry(
            user_id=user_id,
            tier=tier,
            context_type=ContextType.SIGNAL_HISTORY,
            content=summary,
            importance=max(e.importance_score for e in entries),
            metadata={"folded_from": entry_ids},
        )
        
        folded.is_folded = True
        folded.folded_from_entries = entry_ids
        
        await self.db.commit()
        
        logger.info(f"Folded {len(entries)} entries into 1 summary")
        
        return folded
    
    async def cleanup_expired(self, user_id: int) -> int:
        """
        Remove expired entries.
        
        Returns:
            Number of entries removed
        """
        now = datetime.now(timezone.utc)
        
        stmt = select(MemoryEntry).where(
            and_(
                MemoryEntry.user_id == user_id,
                MemoryEntry.expires_at < now,
            )
        )
        result = await self.db.execute(stmt)
        expired = result.scalars().all()
        
        count = len(expired)
        for entry in expired:
            await self.db.delete(entry)
        
        await self.db.commit()
        
        if count > 0:
            logger.info(f"Cleaned up {count} expired entries")
        
        return count
    
    async def _get_tier_usage(self, user_id: int, tier: MemoryTier) -> int:
        """Get current token usage for a tier."""
        stmt = select(func.sum(MemoryEntry.token_count)).where(
            and_(
                MemoryEntry.user_id == user_id,
                MemoryEntry.tier == tier.value,
                MemoryEntry.is_folded == False,
            )
        )
        result = await self.db.execute(stmt)
        usage = result.scalar() or 0
        return usage
    
    async def _make_space(
        self,
        user_id: int,
        tier: MemoryTier,
        needed_tokens: int,
    ):
        """Make space in a tier by folding or removing entries."""
        budget = self.TIER_BUDGETS[tier]
        
        # Get foldable entries (low importance, old)
        stmt = select(MemoryEntry).where(
            and_(
                MemoryEntry.user_id == user_id,
                MemoryEntry.tier == tier.value,
                MemoryEntry.is_folded == False,
            )
        ).order_by(MemoryEntry.importance_score, MemoryEntry.created_at)
        
        result = await self.db.execute(stmt)
        entries = result.scalars().all()
        
        if len(entries) < 3:
            # Not enough to fold, delete oldest
            for entry in entries[:2]:
                await self.db.delete(entry)
            await self.db.commit()
            return
        
        # Fold oldest 5 entries
        to_fold = entries[:5]
        await self.fold_entries(user_id, tier, [e.id for e in to_fold])
    
    def _generate_summary(self, entries: List[MemoryEntry]) -> str:
        """Generate a summary of multiple entries."""
        # Simple rule-based summarization
        # In production, use LLM for better summaries
        
        parts = [f"[Summary of {len(entries)} entries]"]
        
        # Group by context type
        by_type: Dict[str, List[MemoryEntry]] = {}
        for entry in entries:
            by_type.setdefault(entry.context_type, []).append(entry)
        
        for context_type, type_entries in by_type.items():
            parts.append(f"\n{context_type}:")
            
            # Extract key information
            if context_type == ContextType.MARKET_PATTERN.value:
                patterns = [e.content[:100] + "..." for e in type_entries[-3:]]
                parts.extend(f"  - {p}" for p in patterns)
            elif context_type == ContextType.INTENT_HISTORY.value:
                intents = [e.content[:80] + "..." for e in type_entries[-3:]]
                parts.extend(f"  - {i}" for i in intents)
            else:
                # Generic summary
                parts.append(f"  {len(type_entries)} entries of type {context_type}")
        
        parts.append(f"\nTime range: {entries[0].created_at.date()} to {entries[-1].created_at.date()}")
        
        return "\n".join(parts)
    
    async def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get memory usage statistics."""
        stats = {}
        
        for tier in MemoryTier:
            stmt = select(
                func.count(MemoryEntry.id),
                func.sum(MemoryEntry.token_count),
                func.avg(MemoryEntry.importance_score),
            ).where(
                and_(
                    MemoryEntry.user_id == user_id,
                    MemoryEntry.tier == tier.value,
                )
            )
            result = await self.db.execute(stmt)
            count, tokens, avg_importance = result.first()
            
            stats[tier.value] = {
                "entries": count or 0,
                "tokens": tokens or 0,
                "budget": self.TIER_BUDGETS[tier],
                "usage_pct": (tokens or 0) / self.TIER_BUDGETS[tier] * 100,
                "avg_importance": round(avg_importance or 0, 3),
            }
        
        return stats
