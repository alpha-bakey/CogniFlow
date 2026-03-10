"""
Pattern Detector - Technical pattern detection algorithms.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

from cogniflow.models.database import SignalType, SignalSeverity

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    """Result of pattern detection."""
    signal_type: SignalType
    symbol: str
    confidence: float
    severity: SignalSeverity
    price_at_signal: float
    price_reference: Optional[float] = None
    volume_at_signal: Optional[float] = None
    description: str = ""
    indicators: Dict[str, Any] = field(default_factory=dict)
    
    def to_signal_dict(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Convert to dictionary for MarketSignal creation."""
        return {
            "user_id": user_id,
            "signal_type": self.signal_type.value,
            "symbol": self.symbol,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "price_at_signal": self.price_at_signal,
            "price_reference": self.price_reference,
            "volume_at_signal": self.volume_at_signal,
            "description": self.description,
            "indicators_snapshot": self.indicators,
        }


class PatternDetector:
    """
    Detects market patterns from OHLCV data.
    
    Supported patterns:
    - Price Anomaly (Bollinger Band breaches)
    - Volume Spike
    - Volatility Change
    - Moving Average Cross
    - Support/Resistance Touch
    """
    
    def __init__(
        self,
        price_anomaly_threshold: float = 2.5,
        volume_spike_threshold: float = 2.0,
        volatility_change_threshold: float = 0.5,
    ):
        self.price_anomaly_threshold = price_anomaly_threshold
        self.volume_spike_threshold = volume_spike_threshold
        self.volatility_change_threshold = volatility_change_threshold
    
    def detect_all(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> List[DetectionResult]:
        """
        Run all detection algorithms on the data.
        
        Args:
            df: OHLCV DataFrame with technical indicators
            symbol: Stock symbol
            
        Returns:
            List of detected patterns
        """
        results = []
        
        detectors = [
            self.detect_price_anomaly,
            self.detect_volume_spike,
            self.detect_volatility_change,
            self.detect_ma_cross,
            self.detect_support_resistance_touch,
        ]
        
        for detector in detectors:
            try:
                result = detector(df, symbol)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Detector {detector.__name__} failed: {e}")
        
        return results
    
    def detect_price_anomaly(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> Optional[DetectionResult]:
        """
        Detect price anomalies using Bollinger Bands.
        
        Price touching or exceeding Bollinger Bands indicates
        potential overbought/oversold conditions.
        """
        if len(df) < 20:
            return None
        
        latest = df.iloc[-1]
        
        # Check required indicators
        if not all(k in latest for k in ['bb_upper', 'bb_lower', 'ma_20']):
            return None
        
        close = latest['close']
        bb_upper = latest['bb_upper']
        bb_lower = latest['bb_lower']
        ma_20 = latest['ma_20']
        
        # Calculate Z-score
        std_20 = df['close'].rolling(20).std().iloc[-1]
        z_score = (close - ma_20) / std_20 if std_20 > 0 else 0
        
        # Check breach
        if close > bb_upper:
            deviation = (close - bb_upper) / (bb_upper - ma_20)
            confidence = min(0.5 + deviation * 0.3, 0.95)
            
            return DetectionResult(
                signal_type=SignalType.PRICE_ANOMALY,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=self._z_score_to_severity(abs(z_score)),
                price_at_signal=close,
                price_reference=ma_20,
                volume_at_signal=latest.get('volume'),
                description=f"Price {close:.2f} above upper Bollinger Band ({bb_upper:.2f})",
                indicators={
                    "z_score": round(z_score, 2),
                    "bb_position": "above_upper",
                    "rsi": latest.get('rsi_14'),
                }
            )
        
        elif close < bb_lower:
            deviation = (bb_lower - close) / (ma_20 - bb_lower)
            confidence = min(0.5 + deviation * 0.3, 0.95)
            
            return DetectionResult(
                signal_type=SignalType.PRICE_ANOMALY,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=self._z_score_to_severity(abs(z_score)),
                price_at_signal=close,
                price_reference=ma_20,
                volume_at_signal=latest.get('volume'),
                description=f"Price {close:.2f} below lower Bollinger Band ({bb_lower:.2f})",
                indicators={
                    "z_score": round(z_score, 2),
                    "bb_position": "below_lower",
                    "rsi": latest.get('rsi_14'),
                }
            )
        
        return None
    
    def detect_volume_spike(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> Optional[DetectionResult]:
        """
        Detect unusual volume spikes.
        
        Volume significantly above average indicates
        increased market interest.
        """
        if len(df) < 20:
            return None
        
        latest = df.iloc[-1]
        current_volume = latest['volume']
        
        # Calculate average volume (excluding today)
        avg_volume = df['volume'].iloc[:-1].rolling(20).mean().iloc[-1]
        
        if avg_volume <= 0:
            return None
        
        ratio = current_volume / avg_volume
        
        if ratio > self.volume_spike_threshold:
            confidence = min(0.4 + (ratio - self.volume_spike_threshold) * 0.2, 0.9)
            
            return DetectionResult(
                signal_type=SignalType.VOLUME_SPIKE,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=self._ratio_to_severity(ratio, self.volume_spike_threshold),
                price_at_signal=latest['close'],
                volume_at_signal=current_volume,
                description=f"Volume spike: {ratio:.1f}x average ({current_volume:,.0f})",
                indicators={
                    "volume_ratio": round(ratio, 2),
                    "avg_volume_20d": round(avg_volume, 0),
                }
            )
        
        return None
    
    def detect_volatility_change(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> Optional[DetectionResult]:
        """
        Detect significant volatility changes.
        
        Uses ATR (Average True Range) to measure volatility.
        """
        if len(df) < 30:
            return None
        
        latest = df.iloc[-1]
        
        if 'atr_14' not in latest:
            return None
        
        current_atr = latest['atr_14']
        historical_atr = df['atr_14'].iloc[-20:-1].mean()
        
        if historical_atr <= 0:
            return None
        
        change_ratio = (current_atr - historical_atr) / historical_atr
        
        if abs(change_ratio) > self.volatility_change_threshold:
            direction = "increased" if change_ratio > 0 else "decreased"
            confidence = min(0.5 + abs(change_ratio) * 0.3, 0.9)
            
            return DetectionResult(
                signal_type=SignalType.VOLATILITY_CHANGE,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=self._ratio_to_severity(abs(change_ratio), self.volatility_change_threshold),
                price_at_signal=latest['close'],
                description=f"Volatility {direction}: {abs(change_ratio)*100:.0f}% change",
                indicators={
                    "atr_change_ratio": round(change_ratio, 3),
                    "current_atr": round(current_atr, 2),
                    "historical_atr": round(historical_atr, 2),
                }
            )
        
        return None
    
    def detect_ma_cross(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> Optional[DetectionResult]:
        """
        Detect moving average crossovers.
        
        Golden cross (MA20 > MA50) and death cross (MA20 < MA50).
        """
        if len(df) < 51:
            return None
        
        if not all(k in df.columns for k in ['ma_20', 'ma_50']):
            return None
        
        # Get last two periods
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        
        prev_diff = prev['ma_20'] - prev['ma_50']
        curr_diff = curr['ma_20'] - curr['ma_50']
        
        # Check for cross
        if prev_diff * curr_diff < 0:  # Sign change = cross
            if curr_diff > 0:
                cross_type = "golden"
                description = f"Golden cross: MA20 crossed above MA50"
            else:
                cross_type = "death"
                description = f"Death cross: MA20 crossed below MA50"
            
            # Calculate confidence based on divergence
            divergence = abs(curr_diff) / curr['close']
            confidence = min(0.6 + divergence * 10, 0.95)
            
            return DetectionResult(
                signal_type=SignalType.MA_CROSS,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=SignalSeverity.HIGH,
                price_at_signal=curr['close'],
                description=description,
                indicators={
                    "cross_type": cross_type,
                    "ma_20": round(curr['ma_20'], 2),
                    "ma_50": round(curr['ma_50'], 2),
                    "divergence": round(divergence, 4),
                }
            )
        
        return None
    
    def detect_support_resistance_touch(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> Optional[DetectionResult]:
        """
        Detect price touching support or resistance levels.
        
        Uses recent highs/lows to identify key levels.
        """
        if len(df) < 30:
            return None
        
        latest = df.iloc[-1]
        close = latest['close']
        
        # Calculate support/resistance from recent data
        recent = df.iloc[-30:-1]
        resistance = recent['high'].max()
        support = recent['low'].min()
        
        # Check if price is near support or resistance (within 1%)
        threshold_pct = 0.01
        
        # Near resistance
        if resistance > 0 and abs(close - resistance) / resistance < threshold_pct:
            confidence = 0.7 if close < resistance else 0.85
            
            return DetectionResult(
                signal_type=SignalType.SUPPORT_RESISTANCE_TOUCH,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=SignalSeverity.MEDIUM,
                price_at_signal=close,
                price_reference=resistance,
                description=f"Price {close:.2f} near resistance level {resistance:.2f}",
                indicators={
                    "level_type": "resistance",
                    "level_value": round(resistance, 2),
                    "support": round(support, 2),
                    "distance_pct": round((resistance - close) / resistance * 100, 2),
                }
            )
        
        # Near support
        if support > 0 and abs(close - support) / support < threshold_pct:
            confidence = 0.85 if close >= support else 0.7
            
            return DetectionResult(
                signal_type=SignalType.SUPPORT_RESISTANCE_TOUCH,
                symbol=symbol,
                confidence=round(confidence, 2),
                severity=SignalSeverity.MEDIUM,
                price_at_signal=close,
                price_reference=support,
                description=f"Price {close:.2f} near support level {support:.2f}",
                indicators={
                    "level_type": "support",
                    "level_value": round(support, 2),
                    "resistance": round(resistance, 2),
                    "distance_pct": round((close - support) / support * 100, 2),
                }
            )
        
        return None
    
    def _z_score_to_severity(self, z_score: float) -> SignalSeverity:
        """Convert Z-score to severity level."""
        if z_score > 3.5:
            return SignalSeverity.CRITICAL
        elif z_score > 2.5:
            return SignalSeverity.HIGH
        elif z_score > 2.0:
            return SignalSeverity.MEDIUM
        return SignalSeverity.LOW
    
    def _ratio_to_severity(self, ratio: float, threshold: float) -> SignalSeverity:
        """Convert ratio to severity level."""
        excess = ratio - threshold
        if excess > threshold * 2:
            return SignalSeverity.CRITICAL
        elif excess > threshold:
            return SignalSeverity.HIGH
        elif excess > threshold * 0.5:
            return SignalSeverity.MEDIUM
        return SignalSeverity.LOW
