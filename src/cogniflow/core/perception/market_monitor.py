"""
Market Monitor - Continuous market monitoring and pattern detection.
"""
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Set, Callable

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from cogniflow.config import settings
from cogniflow.core.perception.pattern_detector import PatternDetector, DetectionResult
from cogniflow.core.redis_queue import RedisMessageQueue
from cogniflow.models.database import MarketSignal, MarketSnapshot, SignalType

logger = logging.getLogger(__name__)


class PerceptionModule:
    """
    Perception Module - Continuous market monitoring and pattern detection.
    
    This module:
    1. Fetches market data from external sources
    2. Calculates technical indicators
    3. Detects patterns using PatternDetector
    4. Publishes signals to Redis for Intent Prediction Module
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        fmp_client: Optional[object] = None,
        detector: Optional[PatternDetector] = None,
        monitoring_interval: int = 60,
        redis_url: Optional[str] = None,
    ):
        self.db = db_session
        self.fmp_client = fmp_client
        self.detector = detector or PatternDetector(
            price_anomaly_threshold=settings.price_anomaly_threshold,
            volume_spike_threshold=settings.volume_spike_threshold,
        )
        self.monitoring_interval = monitoring_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._symbols: Set[str] = set()
        self._handlers: List[Callable] = []
        
        # Initialize Redis queue
        self._redis = RedisMessageQueue(redis_url or settings.redis_url)
    
    async def initialize(self):
        """Initialize Redis connection."""
        try:
            await self._redis.connect()
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Continuing without Redis.")
            self._redis = None
    
    async def shutdown(self):
        """Cleanup resources."""
        self.stop()
        if self._redis:
            await self._redis.disconnect()
    
    def add_symbols(self, symbols: List[str]):
        """Add symbols to monitor."""
        self._symbols.update(s.upper() for s in symbols)
        logger.info(f"Added {len(symbols)} symbols. Total: {len(self._symbols)}")
    
    def remove_symbol(self, symbol: str):
        """Remove a symbol from monitoring."""
        self._symbols.discard(symbol.upper())
    
    def on_signal(self, handler: Callable):
        """Register a signal handler."""
        self._handlers.append(handler)
    
    async def start(self):
        """Start continuous monitoring."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info(f"PerceptionModule started. Monitoring {len(self._symbols)} symbols")
    
    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
    
    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._monitor_tick()
                await asyncio.sleep(self.monitoring_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(5)
    
    async def _monitor_tick(self):
        """Process one monitoring tick for all symbols."""
        for symbol in self._symbols:
            try:
                await self.analyze_symbol(symbol)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
    
    async def analyze_symbol(
        self,
        symbol: str,
        user_id: Optional[int] = None,
    ) -> List[DetectionResult]:
        """
        Analyze a single symbol and detect patterns.
        
        Args:
            symbol: Stock symbol to analyze
            user_id: Optional user ID for user-specific signals
            
        Returns:
            List of detected patterns
        """
        symbol = symbol.upper()
        
        # Fetch data
        if self.fmp_client:
            df = await self._fetch_from_fmp(symbol)
        else:
            # Use mock data for demo
            df = self._generate_mock_data(symbol)
        
        if df is None or len(df) < 20:
            return []
        
        # Calculate indicators
        df = self._calculate_indicators(df)
        
        # Save snapshot
        await self._save_snapshot(df, symbol, user_id)
        
        # Detect patterns
        results = self.detector.detect_all(df, symbol)
        
        # Process each signal
        for result in results:
            await self._process_signal(result, user_id)
        
        return results
    
    async def _process_signal(
        self,
        result: DetectionResult,
        user_id: Optional[int] = None,
    ):
        """Process a detected signal."""
        # Check for duplicates (within 4 hours)
        existing = await self._find_similar_signal(result, user_id)
        if existing:
            logger.debug(f"Duplicate signal ignored: {result.signal_type.value} for {result.symbol}")
            return
        
        # Create signal entity
        signal = MarketSignal(
            user_id=user_id,
            signal_type=result.signal_type.value,
            symbol=result.symbol,
            severity=result.severity.value,
            confidence=result.confidence,
            price_at_signal=result.price_at_signal,
            price_reference=result.price_reference,
            volume_at_signal=result.volume_at_signal,
            description=result.description,
            indicators_snapshot=result.indicators,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        
        self.db.add(signal)
        await self.db.commit()
        
        logger.info(
            f"Signal detected: {result.signal_type.value} for {result.symbol} "
            f"({result.severity.value}, confidence={result.confidence:.2f})"
        )
        
        # Publish to Redis
        if self._redis:
            await self._redis.publish_market_signal({
                "signal_id": signal.id,
                "signal_type": signal.signal_type,
                "symbol": signal.symbol,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "price": signal.price_at_signal,
                "user_id": user_id,
            })
        
        # Call handlers
        for handler in self._handlers:
            try:
                await handler(result)
            except Exception as e:
                logger.error(f"Signal handler error: {e}")
    
    async def _find_similar_signal(
        self,
        result: DetectionResult,
        user_id: Optional[int] = None,
    ) -> Optional[MarketSignal]:
        """Check for similar recent signal to avoid duplicates."""
        four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=4)
        
        stmt = select(MarketSignal).where(
            and_(
                MarketSignal.symbol == result.symbol,
                MarketSignal.signal_type == result.signal_type.value,
                MarketSignal.created_at >= four_hours_ago,
                MarketSignal.user_id == user_id,
            )
        )
        
        result_proxy = await self.db.execute(stmt)
        return result_proxy.scalar_one_or_none()
    
    async def _save_snapshot(
        self,
        df: pd.DataFrame,
        symbol: str,
        user_id: Optional[int] = None,
    ):
        """Save market snapshot to database."""
        latest = df.iloc[-1]
        
        snapshot = MarketSnapshot(
            user_id=user_id,
            symbol=symbol,
            timestamp=pd.to_datetime(latest['date']),
            price=latest['close'],
            volume=latest['volume'],
            ma_20=latest.get('ma_20'),
            ma_50=latest.get('ma_50'),
            rsi_14=latest.get('rsi_14'),
            bb_upper=latest.get('bb_upper'),
            bb_lower=latest.get('bb_lower'),
            atr_14=latest.get('atr_14'),
            volatility=latest.get('volatility'),
        )
        
        self.db.add(snapshot)
    
    async def _fetch_from_fmp(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch historical data from FMP API."""
        if not self.fmp_client:
            return None
        
        try:
            data = await self.fmp_client.get_historical_price(symbol, period="3month")
            if not data:
                return None
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            return df
            
        except Exception as e:
            logger.error(f"FMP fetch error for {symbol}: {e}")
            return None
    
    def _generate_mock_data(self, symbol: str) -> pd.DataFrame:
        """Generate mock market data for testing."""
        import numpy as np
        
        np.random.seed(42)
        days = 90
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        
        # Generate price series
        returns = np.random.normal(0.001, 0.02, days)
        prices = 100 * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame({
            'date': dates,
            'open': prices * (1 + np.random.normal(0, 0.005, days)),
            'high': prices * (1 + np.random.normal(0.01, 0.005, days)),
            'low': prices * (1 - np.random.normal(0.01, 0.005, days)),
            'close': prices,
            'volume': np.random.randint(1_000_000, 10_000_000, days),
        })
        
        # Ensure high >= close >= low
        df['high'] = df[['high', 'close']].max(axis=1)
        df['low'] = df[['low', 'close']].min(axis=1)
        df['open'] = df[['high', 'open', 'low']].clip(axis=1)
        
        return df
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators."""
        df = df.copy()
        
        # Moving averages
        df['ma_20'] = df['close'].rolling(window=20).mean()
        df['ma_50'] = df['close'].rolling(window=50).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi_14'] = 100 - (100 / (1 + rs))
        
        # Bollinger Bands
        df['std_20'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['ma_20'] + (df['std_20'] * 2)
        df['bb_lower'] = df['ma_20'] - (df['std_20'] * 2)
        
        # ATR (Average True Range)
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(window=14).mean()
        
        # Volatility (standard deviation of returns)
        df['returns'] = df['close'].pct_change()
        df['volatility'] = df['returns'].rolling(window=20).std() * (252 ** 0.5)
        
        return df
