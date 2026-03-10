"""
Intent Generator - Generates candidate intents from market signals.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from cogniflow.models.database import SignalType, IntentType

logger = logging.getLogger(__name__)


@dataclass
class CandidateIntent:
    """A candidate intent generated from market signals."""
    intent_type: IntentType
    confidence: float
    urgency: float
    target_symbol: str
    trigger_signals: List[int] = field(default_factory=list)
    proposed_action: Optional[Dict[str, Any]] = None
    reasoning: str = ""
    
    @property
    def priority_score(self) -> float:
        """Calculate priority score."""
        return self.confidence * 0.4 + self.urgency * 0.6
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent_type": self.intent_type.value,
            "confidence": self.confidence,
            "urgency": self.urgency,
            "target_symbol": self.target_symbol,
            "trigger_signals": self.trigger_signals,
            "proposed_action": self.proposed_action,
            "reasoning": self.reasoning,
            "priority_score": self.priority_score,
        }


class IntentGenerator:
    """
    Generates candidate trading intents from market signals.
    
    Maps signal types to intent types using rule-based templates.
    """
    
    def __init__(self, min_confidence: float = 0.6):
        self.min_confidence = min_confidence
        
        # Signal type to intent type mapping
        self._signal_intent_map = {
            SignalType.PRICE_ANOMALY: self._handle_price_anomaly,
            SignalType.VOLUME_SPIKE: self._handle_volume_spike,
            SignalType.VOLATILITY_CHANGE: self._handle_volatility_change,
            SignalType.MA_CROSS: self._handle_ma_cross,
            SignalType.SUPPORT_RESISTANCE_TOUCH: self._handle_sr_touch,
        }
    
    async def generate_candidates(
        self,
        signals: List[Any],
        portfolio: Dict[str, Any],
        max_candidates: int = 3,
    ) -> List[CandidateIntent]:
        """
        Generate candidate intents from market signals.
        
        Args:
            signals: List of market signals
            portfolio: User's portfolio information
            max_candidates: Maximum number of candidates to return
            
        Returns:
            List of candidate intents sorted by priority
        """
        candidates = []
        
        for signal in signals:
            handler = self._signal_intent_map.get(self._get_signal_type(signal))
            if handler:
                try:
                    intent = handler(signal, portfolio)
                    if intent and intent.confidence >= self.min_confidence:
                        candidates.append(intent)
                except Exception as e:
                    logger.error(f"Intent generation error: {e}")
        
        # Sort by priority score and return top N
        candidates.sort(key=lambda x: x.priority_score, reverse=True)
        return candidates[:max_candidates]
    
    def _get_signal_type(self, signal: Any) -> SignalType:
        """Extract signal type from signal object."""
        if isinstance(signal.signal_type, SignalType):
            return signal.signal_type
        return SignalType(signal.signal_type)
    
    def _has_position(self, portfolio: Dict, symbol: str) -> bool:
        """Check if user has position in symbol."""
        holdings = portfolio.get("holdings", {})
        return symbol in holdings and holdings[symbol].get("quantity", 0) > 0
    
    def _get_position(self, portfolio: Dict, symbol: str) -> Dict:
        """Get position details for symbol."""
        return portfolio.get("holdings", {}).get(symbol, {})
    
    def _handle_price_anomaly(
        self,
        signal: Any,
        portfolio: Dict[str, Any],
    ) -> Optional[CandidateIntent]:
        """Handle price anomaly signals."""
        symbol = signal.symbol
        indicators = signal.indicators_snapshot or {}
        bb_position = indicators.get("bb_position", "")
        
        if self._has_position(portfolio, symbol):
            # Position exists - consider taking profit or adding
            position = self._get_position(portfolio, symbol)
            avg_cost = position.get("avg_cost", 0)
            current_price = signal.price_at_signal
            
            if bb_position == "above_upper" and current_price > avg_cost * 1.05:
                # Significant profit - suggest taking profit
                return CandidateIntent(
                    intent_type=IntentType.TAKE_PROFIT,
                    confidence=signal.confidence * 0.9,
                    urgency=0.6,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "SELL",
                        "symbol": symbol,
                        "suggested_percentage": 0.25,
                        "reason": "Price above upper BB with profit",
                    },
                    reasoning=f"Price ${current_price:.2f} is above upper Bollinger Band with {((current_price/avg_cost-1)*100):.1f}% gain",
                )
            elif bb_position == "below_lower":
                # Potential dip buying opportunity
                return CandidateIntent(
                    intent_type=IntentType.BUY_DIP,
                    confidence=signal.confidence * 0.85,
                    urgency=0.5,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "BUY",
                        "symbol": symbol,
                        "suggested_amount": "$1,000",
                        "reason": "Price below lower BB - potential dip",
                    },
                    reasoning=f"Price ${current_price:.2f} below lower Bollinger Band - potential buying opportunity",
                )
        else:
            # No position
            if bb_position == "below_lower":
                return CandidateIntent(
                    intent_type=IntentType.BUY_DIP,
                    confidence=signal.confidence * 0.8,
                    urgency=0.4,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "BUY",
                        "symbol": symbol,
                        "suggested_amount": "$1,000",
                        "reason": "Potential entry point",
                    },
                    reasoning=f"Price ${signal.price_at_signal:.2f} below lower Bollinger Band - potential entry",
                )
        
        return None
    
    def _handle_volume_spike(
        self,
        signal: Any,
        portfolio: Dict[str, Any],
    ) -> Optional[CandidateIntent]:
        """Handle volume spike signals."""
        symbol = signal.symbol
        indicators = signal.indicators_snapshot or {}
        volume_ratio = indicators.get("volume_ratio", 1.0)
        
        # High volume often precedes significant moves
        if self._has_position(portfolio, symbol) and volume_ratio > 3.0:
            return CandidateIntent(
                intent_type=IntentType.INFO_SEEKING,
                confidence=signal.confidence * 0.7,
                urgency=0.6,
                target_symbol=symbol,
                trigger_signals=[signal.id],
                proposed_action={
                    "action": "RESEARCH",
                    "symbol": symbol,
                    "reason": f"Unusual volume ({volume_ratio:.1f}x average)",
                },
                reasoning=f"Volume spike of {volume_ratio:.1f}x average detected - may indicate news or events",
            )
        
        return None
    
    def _handle_volatility_change(
        self,
        signal: Any,
        portfolio: Dict[str, Any],
    ) -> Optional[CandidateIntent]:
        """Handle volatility change signals."""
        symbol = signal.symbol
        indicators = signal.indicators_snapshot or {}
        atr_change = indicators.get("atr_change_ratio", 0)
        
        if abs(atr_change) > 0.5 and self._has_position(portfolio, symbol):
            # Significant volatility change - review risk
            return CandidateIntent(
                intent_type=IntentType.REDUCE_RISK,
                confidence=signal.confidence * 0.75,
                urgency=0.7 if atr_change > 0 else 0.4,
                target_symbol=symbol,
                trigger_signals=[signal.id],
                proposed_action={
                    "action": "REVIEW_POSITION",
                    "symbol": symbol,
                    "reason": f"Volatility {'increased' if atr_change > 0 else 'decreased'} significantly",
                },
                reasoning=f"ATR changed by {abs(atr_change)*100:.0f}% - consider adjusting position size",
            )
        
        return None
    
    def _handle_ma_cross(
        self,
        signal: Any,
        portfolio: Dict[str, Any],
    ) -> Optional[CandidateIntent]:
        """Handle moving average crossover signals."""
        symbol = signal.symbol
        indicators = signal.indicators_snapshot or {}
        cross_type = indicators.get("cross_type", "")
        
        if cross_type == "golden":
            # Bullish signal
            if not self._has_position(portfolio, symbol):
                return CandidateIntent(
                    intent_type=IntentType.ADD_POSITION,
                    confidence=signal.confidence * 0.8,
                    urgency=0.6,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "BUY",
                        "symbol": symbol,
                        "suggested_amount": "$1,000",
                        "reason": "Golden cross - bullish momentum",
                    },
                    reasoning="MA20 crossed above MA50 (golden cross) - potential uptrend starting",
                )
            else:
                return CandidateIntent(
                    intent_type=IntentType.ADD_POSITION,
                    confidence=signal.confidence * 0.7,
                    urgency=0.4,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "ADD",
                        "symbol": symbol,
                        "suggested_percentage": 0.1,
                        "reason": "Golden cross - add to position",
                    },
                    reasoning="Golden cross with existing position - consider adding",
                )
        
        elif cross_type == "death":
            # Bearish signal
            if self._has_position(portfolio, symbol):
                return CandidateIntent(
                    intent_type=IntentType.STOP_PROFIT_LOSS,
                    confidence=signal.confidence * 0.85,
                    urgency=0.7,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "REVIEW_STOPS",
                        "symbol": symbol,
                        "reason": "Death cross - bearish signal",
                    },
                    reasoning="MA20 crossed below MA50 (death cross) - consider tightening stops",
                )
        
        return None
    
    def _handle_sr_touch(
        self,
        signal: Any,
        portfolio: Dict[str, Any],
    ) -> Optional[CandidateIntent]:
        """Handle support/resistance touch signals."""
        symbol = signal.symbol
        indicators = signal.indicators_snapshot or {}
        level_type = indicators.get("level_type", "")
        
        if level_type == "support":
            if not self._has_position(portfolio, symbol):
                return CandidateIntent(
                    intent_type=IntentType.BUY_DIP,
                    confidence=signal.confidence * 0.85,
                    urgency=0.5,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "BUY",
                        "symbol": symbol,
                        "suggested_amount": "$1,000",
                        "reason": "Price at support level",
                    },
                    reasoning=f"Price at support level ${signal.price_reference:.2f} - potential bounce",
                )
            else:
                return CandidateIntent(
                    intent_type=IntentType.HOLD_WAIT,
                    confidence=signal.confidence * 0.7,
                    urgency=0.3,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "HOLD",
                        "symbol": symbol,
                        "reason": "Price at support - hold position",
                    },
                    reasoning=f"Support level test - maintain position with tight stops",
                )
        
        elif level_type == "resistance":
            if self._has_position(portfolio, symbol):
                return CandidateIntent(
                    intent_type=IntentType.TAKE_PROFIT,
                    confidence=signal.confidence * 0.8,
                    urgency=0.5,
                    target_symbol=symbol,
                    trigger_signals=[signal.id],
                    proposed_action={
                        "action": "SELL_PARTIAL",
                        "symbol": symbol,
                        "suggested_percentage": 0.25,
                        "reason": "Price at resistance level",
                    },
                    reasoning=f"Price at resistance level ${signal.price_reference:.2f} - consider taking some profit",
                )
        
        return None
