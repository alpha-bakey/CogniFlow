"""
Tests for Intent Prediction Module.
"""
import pytest
import pytest_asyncio

from cogniflow.core.intent import IntentGenerator, IntentEvaluator
from cogniflow.core.intent.generator import CandidateIntent
from cogniflow.models.database import IntentType, SignalType


class MockSignal:
    """Mock market signal for testing."""
    def __init__(self, signal_type, symbol, confidence=0.8):
        self.id = 1
        self.signal_type = signal_type
        self.symbol = symbol
        self.confidence = confidence
        self.price_at_signal = 150.0
        self.indicators_snapshot = {}


class TestIntentGenerator:
    """Test cases for IntentGenerator."""
    
    @pytest.fixture
    def generator(self):
        return IntentGenerator(min_confidence=0.6)
    
    @pytest.fixture
    def empty_portfolio(self):
        return {"holdings": {}, "cash": 10000}
    
    @pytest.fixture
    def with_position_portfolio(self):
        return {
            "holdings": {
                "AAPL": {"quantity": 100, "avg_cost": 140.0, "value": 15000}
            },
            "cash": 5000,
        }
    
    @pytest.mark.asyncio
    async def test_generator_initialization(self, generator):
        """Test generator can be initialized."""
        assert generator.min_confidence == 0.6
    
    @pytest.mark.asyncio
    async def test_generate_candidates_empty(self, generator, empty_portfolio):
        """Test generating candidates with no signals."""
        candidates = await generator.generate_candidates(
            signals=[],
            portfolio=empty_portfolio,
        )
        assert candidates == []
    
    @pytest.mark.asyncio
    async def test_price_anomaly_without_position(self, generator, empty_portfolio):
        """Test intent generation for price anomaly without position."""
        signal = MockSignal(SignalType.PRICE_ANOMALY, "AAPL")
        signal.indicators_snapshot = {"bb_position": "below_lower"}
        
        candidates = await generator.generate_candidates(
            signals=[signal],
            portfolio=empty_portfolio,
        )
        
        # May generate BUY_DIP intent
        for c in candidates:
            assert c.confidence >= 0.6
            assert c.target_symbol == "AAPL"
    
    @pytest.mark.asyncio
    async def test_price_anomaly_with_position(self, generator, with_position_portfolio):
        """Test intent generation for price anomaly with existing position."""
        signal = MockSignal(SignalType.PRICE_ANOMALY, "AAPL")
        signal.confidence = 0.9
        signal.price_at_signal = 175.0  # Above avg cost
        signal.indicators_snapshot = {"bb_position": "above_upper"}
        
        candidates = await generator.generate_candidates(
            signals=[signal],
            portfolio=with_position_portfolio,
        )
        
        # May generate TAKE_PROFIT intent
        for c in candidates:
            assert c.confidence >= 0.6


class TestIntentEvaluator:
    """Test cases for IntentEvaluator."""
    
    @pytest.fixture
    def evaluator(self):
        return IntentEvaluator(min_overall_score=0.5)
    
    @pytest.fixture
    def sample_intent(self):
        return CandidateIntent(
            intent_type=IntentType.BUY_DIP,
            confidence=0.8,
            urgency=0.6,
            target_symbol="AAPL",
            reasoning="Price below support",
        )
    
    @pytest.fixture
    def sample_user_context(self):
        return {
            "risk_profile": "moderate",
            "watchlist": ["AAPL", "MSFT"],
            "preferred_intent_types": ["BUY_DIP", "TAKE_PROFIT"],
        }
    
    @pytest.fixture
    def sample_portfolio(self):
        return {
            "holdings": {"AAPL": {"quantity": 50, "value": 7500}},
            "total_value": 20000,
        }
    
    @pytest.mark.asyncio
    async def test_evaluator_initialization(self, evaluator):
        """Test evaluator can be initialized."""
        assert evaluator.min_overall_score == 0.5
    
    @pytest.mark.asyncio
    async def test_evaluate_intent(self, evaluator, sample_intent, sample_user_context, sample_portfolio):
        """Test intent evaluation."""
        result = await evaluator.evaluate(
            intent=sample_intent,
            user_context=sample_user_context,
            portfolio=sample_portfolio,
            recent_intents=[],
        )
        
        assert result.intent_type == "BUY_DIP"
        assert 0 <= result.overall_score <= 1
        assert "relevance" in result.scores
        assert "urgency" in result.scores
        assert "risk_assessment" in result.scores
        assert isinstance(result.should_recommend, bool)
    
    @pytest.mark.asyncio
    async def test_evaluate_risky_intent(self, evaluator, sample_user_context):
        """Test evaluation of high-risk intent."""
        # Create concentrated position intent
        intent = CandidateIntent(
            intent_type=IntentType.ADD_POSITION,
            confidence=0.7,
            urgency=0.5,
            target_symbol="AAPL",
        )
        
        # Portfolio already heavily concentrated in AAPL
        concentrated_portfolio = {
            "holdings": {
                "AAPL": {"quantity": 500, "value": 75000},
            },
            "total_value": 80000,  # 93% in AAPL
        }
        
        result = await evaluator.evaluate(
            intent=intent,
            user_context=sample_user_context,
            portfolio=concentrated_portfolio,
            recent_intents=[],
        )
        
        # Should have lower risk score due to concentration
        assert result.scores["risk_assessment"] < 0.8
