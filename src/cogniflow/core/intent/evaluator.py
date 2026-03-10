"""
Intent Evaluator - Multi-dimensional intent evaluation.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from cogniflow.models.database import IntentType

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of intent evaluation."""
    intent_type: str
    overall_score: float
    should_recommend: bool
    scores: Dict[str, float] = field(default_factory=dict)
    reasoning: str = ""
    risk_flags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent_type": self.intent_type,
            "overall_score": self.overall_score,
            "should_recommend": self.should_recommend,
            "scores": self.scores,
            "reasoning": self.reasoning,
            "risk_flags": self.risk_flags,
        }


class IntentEvaluator:
    """
    Evaluates candidate intents across 5 dimensions:
    
    1. Relevance - Match to user's portfolio and preferences
    2. Urgency - Time-sensitivity of the opportunity
    3. Information Gap - Need for additional research
    4. Consistency - Alignment with recent user actions
    5. Risk Assessment - Suitability for user's risk profile
    """
    
    def __init__(
        self,
        min_overall_score: float = 0.5,
        min_risk_score: float = 0.3,
    ):
        self.min_overall_score = min_overall_score
        self.min_risk_score = min_risk_score
    
    async def evaluate(
        self,
        intent: Any,
        user_context: Dict[str, Any],
        portfolio: Dict[str, Any],
        recent_intents: Optional[List[Dict]] = None,
    ) -> EvaluationResult:
        """
        Evaluate a candidate intent.
        
        Args:
            intent: The candidate intent to evaluate
            user_context: User preferences and behavior
            portfolio: User's portfolio
            recent_intents: Recent intent history
            
        Returns:
            Evaluation result with scores and recommendation
        """
        recent_intents = recent_intents or []
        
        # Calculate dimension scores
        scores = {
            "relevance": self._assess_relevance(intent, portfolio, user_context),
            "urgency": self._assess_urgency(intent, user_context),
            "information_gap": self._assess_info_gap(intent, user_context),
            "consistency": self._assess_consistency(intent, recent_intents),
            "risk_assessment": self._assess_risk(intent, user_context, portfolio),
        }
        
        # Calculate overall score (weighted average)
        weights = {
            "relevance": 0.25,
            "urgency": 0.20,
            "information_gap": 0.15,
            "consistency": 0.15,
            "risk_assessment": 0.25,
        }
        
        overall_score = sum(
            scores[dim] * weight for dim, weight in weights.items()
        )
        
        # Identify risk flags
        risk_flags = self._identify_risk_flags(intent, scores)
        
        # Generate reasoning
        reasoning = self._generate_reasoning(intent, overall_score, scores, risk_flags)
        
        # Determine if should recommend
        should_recommend = (
            overall_score >= self.min_overall_score and
            scores["risk_assessment"] >= self.min_risk_score and
            len(risk_flags) <= 1
        )
        
        return EvaluationResult(
            intent_type=intent.intent_type.value,
            overall_score=round(overall_score, 3),
            should_recommend=should_recommend,
            scores={k: round(v, 3) for k, v in scores.items()},
            reasoning=reasoning,
            risk_flags=risk_flags,
        )
    
    def _assess_relevance(
        self,
        intent: Any,
        portfolio: Dict[str, Any],
        user_context: Dict[str, Any],
    ) -> float:
        """
        Assess relevance to user's portfolio and preferences.
        
        Returns:
            Score 0-1, higher is more relevant
        """
        score = 0.5  # Base score
        
        symbol = intent.target_symbol
        intent_type = intent.intent_type
        
        # Check watchlist
        watchlist = user_context.get("watchlist", [])
        portfolio_symbols = list(portfolio.get("holdings", {}).keys())
        preferred_symbols = user_context.get("preferred_symbols", [])
        
        # Strong relevance if in portfolio
        if symbol in portfolio_symbols:
            score += 0.3
        
        # Moderate relevance if on watchlist
        elif symbol in watchlist:
            score += 0.15
        
        # Small relevance if preferred
        elif symbol in preferred_symbols:
            score += 0.1
        
        # Check intent type preference
        preferred_intents = user_context.get("preferred_intent_types", [])
        if intent_type.value in preferred_intents:
            score += 0.15
        
        # Adjust based on confidence
        score += intent.confidence * 0.1
        
        return min(score, 1.0)
    
    def _assess_urgency(
        self,
        intent: Any,
        user_context: Dict[str, Any],
    ) -> float:
        """
        Assess urgency/time-sensitivity.
        
        Returns:
            Score 0-1, higher is more urgent
        """
        base_urgency = intent.urgency
        
        # Check market hours
        market_open = user_context.get("market_open", True)
        if not market_open:
            base_urgency *= 0.7  # Less urgent when market closed
        
        # Check user's quiet hours
        if self._is_quiet_hours(user_context):
            base_urgency *= 0.5
        
        # Intent type urgency adjustments
        urgency_multipliers = {
            IntentType.STOP_PROFIT_LOSS.value: 1.2,
            IntentType.TAKE_PROFIT.value: 1.1,
            IntentType.REDUCE_RISK.value: 1.15,
            IntentType.INFO_SEEKING.value: 0.8,
            IntentType.HOLD_WAIT.value: 0.6,
        }
        
        multiplier = urgency_multipliers.get(intent.intent_type.value, 1.0)
        
        return min(base_urgency * multiplier, 1.0)
    
    def _assess_info_gap(
        self,
        intent: Any,
        user_context: Dict[str, Any],
    ) -> float:
        """
        Assess information gap.
        
        Returns:
            Score 0-1, higher means less info gap (better)
        """
        # Higher score = less gap = more ready to act
        score = 0.7  # Base assumption: reasonably informed
        
        # Check if user has recent research on this symbol
        recent_research = user_context.get("recent_research", [])
        symbol_researched = any(
            r.get("symbol") == intent.target_symbol 
            for r in recent_research[-7:]  # Last 7 days
        )
        
        if symbol_researched:
            score += 0.2
        
        # INFO_SEEKING intents need more research
        if intent.intent_type == IntentType.INFO_SEEKING:
            score -= 0.3
        
        # High confidence signals suggest clear situation
        score += intent.confidence * 0.1
        
        return max(0.0, min(score, 1.0))
    
    def _assess_consistency(
        self,
        intent: Any,
        recent_intents: List[Dict],
    ) -> float:
        """
        Assess consistency with recent user behavior.
        
        Returns:
            Score 0-1, higher is more consistent
        """
        score = 0.7  # Base assumption: mostly consistent
        
        if not recent_intents:
            return score
        
        # Check for conflicting recent intents
        intent_type = intent.intent_type.value
        symbol = intent.target_symbol
        
        conflicting_pairs = [
            (IntentType.BUY_DIP.value, IntentType.TAKE_PROFIT.value),
            (IntentType.ADD_POSITION.value, IntentType.REDUCE_RISK.value),
        ]
        
        for recent in recent_intents[-5:]:  # Last 5 intents
            recent_type = recent.get("intent_type", "")
            recent_symbol = recent.get("target_symbol", "")
            
            # Same symbol, conflicting action
            if recent_symbol == symbol:
                for pair in conflicting_pairs:
                    if (intent_type == pair[0] and recent_type == pair[1]) or \
                       (intent_type == pair[1] and recent_type == pair[0]):
                        score -= 0.2
            
            # Check if recently rejected similar intent
            if recent_type == intent_type and recent_symbol == symbol:
                if recent.get("status") == "REJECTED":
                    score -= 0.15
        
        # Boost for repeated patterns
        similar_count = sum(
            1 for r in recent_intents[-10:]
            if r.get("intent_type") == intent_type
        )
        if similar_count >= 2:
            score += 0.1
        
        return max(0.0, min(score, 1.0))
    
    def _assess_risk(
        self,
        intent: Any,
        user_context: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> float:
        """
        Assess risk suitability for user's profile.
        
        Returns:
            Score 0-1, higher is more suitable
        """
        score = 0.6  # Base score
        
        user_risk = user_context.get("risk_profile", "moderate")
        intent_risk = self._get_intent_risk_level(intent.intent_type)
        
        # Risk profile matching
        risk_scores = {
            "conservative": 1,
            "moderate": 2,
            "aggressive": 3,
        }
        
        user_risk_score = risk_scores.get(user_risk, 2)
        intent_risk_score = risk_scores.get(intent_risk, 2)
        
        # Penalty if intent risk > user risk tolerance
        if intent_risk_score > user_risk_score:
            score -= (intent_risk_score - user_risk_score) * 0.25
        
        # Check portfolio concentration
        holdings = portfolio.get("holdings", {})
        total_value = sum(h.get("value", 0) for h in holdings.values())
        
        symbol_value = holdings.get(intent.target_symbol, {}).get("value", 0)
        
        if total_value > 0:
            concentration = symbol_value / total_value
            
            # Risky to add more to already concentrated position
            if intent.intent_type in [IntentType.ADD_POSITION, IntentType.BUY_DIP]:
                if concentration > 0.25:  # >25% in one stock
                    score -= 0.2
                elif concentration > 0.15:
                    score -= 0.1
        
        # Boost for risk-reducing intents
        if intent.intent_type in [IntentType.REDUCE_RISK, IntentType.DIVERSIFY, IntentType.REVIEW_STOPS]:
            score += 0.15
        
        return max(0.0, min(score, 1.0))
    
    def _identify_risk_flags(
        self,
        intent: Any,
        scores: Dict[str, float],
    ) -> List[str]:
        """Identify risk flags for the intent."""
        flags = []
        
        if scores["risk_assessment"] < 0.4:
            flags.append("HIGH_RISK_FOR_PROFILE")
        
        if scores["consistency"] < 0.4:
            flags.append("INCONSISTENT_WITH_HISTORY")
        
        if scores["information_gap"] < 0.3:
            flags.append("NEEDS_MORE_RESEARCH")
        
        if intent.confidence < 0.6:
            flags.append("LOW_CONFIDENCE")
        
        return flags
    
    def _generate_reasoning(
        self,
        intent: Any,
        overall_score: float,
        scores: Dict[str, float],
        risk_flags: List[str],
    ) -> str:
        """Generate human-readable reasoning."""
        parts = []
        
        # Overall assessment
        if overall_score > 0.8:
            parts.append("Strong candidate")
        elif overall_score > 0.6:
            parts.append("Moderate candidate")
        else:
            parts.append("Weak candidate")
        
        # Key strengths
        strengths = []
        if scores["relevance"] > 0.8:
            strengths.append("highly relevant")
        if scores["urgency"] > 0.7:
            strengths.append("time-sensitive")
        if scores["risk_assessment"] > 0.8:
            strengths.append("good risk fit")
        
        if strengths:
            parts.append(f"Strengths: {', '.join(strengths)}")
        
        # Concerns
        concerns = []
        if scores["consistency"] < 0.5:
            concerns.append("inconsistent with history")
        if scores["information_gap"] < 0.5:
            concerns.append("needs research")
        
        if concerns:
            parts.append(f"Concerns: {', '.join(concerns)}")
        
        if risk_flags:
            parts.append(f"Flags: {', '.join(risk_flags)}")
        
        return "; ".join(parts)
    
    def _is_quiet_hours(self, user_context: Dict[str, Any]) -> bool:
        """Check if current time is in user's quiet hours."""
        import datetime as dt
        
        now = dt.datetime.now().hour
        quiet_start = user_context.get("quiet_hours_start")
        quiet_end = user_context.get("quiet_hours_end")
        
        if quiet_start is None or quiet_end is None:
            return False
        
        if quiet_start <= quiet_end:
            return quiet_start <= now <= quiet_end
        else:
            return now >= quiet_start or now <= quiet_end
    
    def _get_intent_risk_level(self, intent_type: IntentType) -> str:
        """Get risk level for intent type."""
        risk_map = {
            IntentType.BUY_DIP: "moderate",
            IntentType.TAKE_PROFIT: "conservative",
            IntentType.STOP_PROFIT_LOSS: "conservative",
            IntentType.REBALANCE: "moderate",
            IntentType.REDUCE_RISK: "conservative",
            IntentType.HOLD_WAIT: "conservative",
            IntentType.INFO_SEEKING: "conservative",
            IntentType.ADD_POSITION: "aggressive",
            IntentType.DIVERSIFY: "moderate",
            IntentType.REVIEW_STOPS: "moderate",
        }
        return risk_map.get(intent_type, "moderate")
