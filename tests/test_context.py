"""
Tests for Context Management Module.
"""
import pytest
import pytest_asyncio

from cogniflow.core.context import HierarchicalMemoryManager
from cogniflow.models.database import MemoryTier, ContextType


class TestTokenEstimator:
    """Test cases for TokenEstimator."""
    
    def test_estimate_short_text(self):
        """Test token estimation for short text."""
        from cogniflow.core.context.memory_manager import TokenEstimator
        
        estimator = TokenEstimator()
        text = "AAPL price broke above resistance"
        tokens = estimator.estimate(text)
        
        # Rough check: should be positive and proportional to length
        assert tokens > 0
        assert tokens < len(text)  # 1 token < 1 char
    
    def test_estimate_long_text(self):
        """Test token estimation for longer text."""
        from cogniflow.core.context.memory_manager import TokenEstimator
        
        estimator = TokenEstimator()
        text = "This is a much longer text about AAPL stock performance and technical indicators." * 10
        
        tokens = estimator.estimate(text)
        assert tokens > 10


class TestHierarchicalMemoryManager:
    """Test cases for HierarchicalMemoryManager."""
    
    @pytest.mark.asyncio
    async def test_add_entry(self, db_session):
        """Test adding a memory entry."""
        manager = HierarchicalMemoryManager(db_session)
        
        entry = await manager.add_entry(
            user_id=1,
            tier=MemoryTier.WORKING,
            context_type=ContextType.MARKET_PATTERN,
            content="AAPL broke resistance at $175",
            importance=0.8,
        )
        
        assert entry.id is not None
        assert entry.user_id == 1
        assert entry.tier == MemoryTier.WORKING.value
        assert entry.context_type == ContextType.MARKET_PATTERN.value
        assert entry.token_count > 0
        assert entry.importance_score == 0.8
    
    @pytest.mark.asyncio
    async def test_get_entries(self, db_session):
        """Test retrieving memory entries."""
        manager = HierarchicalMemoryManager(db_session)
        
        # Add some entries
        await manager.add_entry(
            user_id=1,
            tier=MemoryTier.WORKING,
            context_type=ContextType.MARKET_PATTERN,
            content="Entry 1",
            importance=0.5,
        )
        await manager.add_entry(
            user_id=1,
            tier=MemoryTier.WORKING,
            context_type=ContextType.INTENT_HISTORY,
            content="Entry 2",
            importance=0.7,
        )
        
        # Get all entries
        entries = await manager.get_entries(user_id=1, tier=MemoryTier.WORKING)
        assert len(entries) >= 2
    
    @pytest.mark.asyncio
    async def test_get_entries_by_type(self, db_session):
        """Test filtering entries by context type."""
        manager = HierarchicalMemoryManager(db_session)
        
        await manager.add_entry(
            user_id=1,
            tier=MemoryTier.WORKING,
            context_type=ContextType.MARKET_PATTERN,
            content="Market pattern entry",
            importance=0.5,
        )
        
        entries = await manager.get_entries(
            user_id=1,
            context_type=ContextType.MARKET_PATTERN,
        )
        
        for entry in entries:
            assert entry.context_type == ContextType.MARKET_PATTERN.value
    
    @pytest.mark.asyncio
    async def test_tier_budgets(self):
        """Test tier budget constants."""
        from cogniflow.core.context.memory_manager import HierarchicalMemoryManager
        
        assert HierarchicalMemoryManager.TIER_BUDGETS[MemoryTier.WORKING] == 4000
        assert HierarchicalMemoryManager.TIER_BUDGETS[MemoryTier.SHORT_TERM] == 16000
        assert HierarchicalMemoryManager.TIER_BUDGETS[MemoryTier.LONG_TERM] == 64000
    
    @pytest.mark.asyncio
    async def test_query_relevant(self, db_session):
        """Test querying relevant context."""
        manager = HierarchicalMemoryManager(db_session)
        
        # Add some context
        await manager.add_entry(
            user_id=1,
            tier=MemoryTier.WORKING,
            context_type=ContextType.MARKET_PATTERN,
            content="AAPL is showing bullish momentum with RSI at 65",
            importance=0.8,
        )
        
        # Query context
        context = await manager.query_relevant(
            user_id=1,
            query="What's happening with AAPL?",
            max_tokens=1000,
        )
        
        # Should return some context
        assert isinstance(context, str)
