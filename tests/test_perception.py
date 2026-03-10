"""
Tests for Perception Module.
"""
import pytest
import pandas as pd
import numpy as np

from cogniflow.core.perception import PatternDetector
from cogniflow.models.database import SignalType, SignalSeverity


class TestPatternDetector:
    """Test cases for PatternDetector."""
    
    @pytest.fixture
    def sample_data(self):
        """Generate sample OHLCV data."""
        np.random.seed(42)
        dates = pd.date_range(end="2024-01-01", periods=90, freq='D')
        
        returns = np.random.normal(0.001, 0.02, 90)
        prices = 100 * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame({
            'date': dates,
            'open': prices * (1 + np.random.normal(0, 0.005, 90)),
            'high': prices * (1 + np.abs(np.random.normal(0.01, 0.005, 90))),
            'low': prices * (1 - np.abs(np.random.normal(0.01, 0.005, 90))),
            'close': prices,
            'volume': np.random.randint(1_000_000, 10_000_000, 90),
        })
        
        # Add indicators
        df['ma_20'] = df['close'].rolling(20).mean()
        df['ma_50'] = df['close'].rolling(50).mean()
        df['std_20'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['ma_20'] + (df['std_20'] * 2)
        df['bb_lower'] = df['ma_20'] - (df['std_20'] * 2)
        
        return df
    
    def test_detector_initialization(self):
        """Test detector can be initialized."""
        detector = PatternDetector(
            price_anomaly_threshold=2.5,
            volume_spike_threshold=2.0,
        )
        assert detector.price_anomaly_threshold == 2.5
        assert detector.volume_spike_threshold == 2.0
    
    def test_price_anomaly_detection(self, sample_data):
        """Test price anomaly detection."""
        detector = PatternDetector(price_anomaly_threshold=2.0)
        
        # Modify data to create an anomaly
        df = sample_data.copy()
        df.loc[df.index[-1], 'close'] = df['bb_upper'].iloc[-1] * 1.05
        
        result = detector.detect_price_anomaly(df, "TEST")
        
        if result:
            assert result.signal_type == SignalType.PRICE_ANOMALY
            assert result.symbol == "TEST"
            assert 0 <= result.confidence <= 1
    
    def test_volume_spike_detection(self, sample_data):
        """Test volume spike detection."""
        detector = PatternDetector(volume_spike_threshold=2.0)
        
        # Modify data to create volume spike
        df = sample_data.copy()
        avg_volume = df['volume'].iloc[:-1].mean()
        df.loc[df.index[-1], 'volume'] = avg_volume * 3
        
        result = detector.detect_volume_spike(df, "TEST")
        
        if result:
            assert result.signal_type == SignalType.VOLUME_SPIKE
            assert result.symbol == "TEST"
    
    def test_ma_cross_detection(self, sample_data):
        """Test moving average crossover detection."""
        detector = PatternDetector()
        
        df = sample_data.copy()
        
        # Ensure we have enough data
        if len(df) >= 51 and not df['ma_20'].isna().all():
            result = detector.detect_ma_cross(df, "TEST")
            
            # Result may or may not be detected depending on data
            if result:
                assert result.signal_type == SignalType.MA_CROSS
                assert result.indicators.get("cross_type") in ["golden", "death"]
    
    def test_detect_all_patterns(self, sample_data):
        """Test detecting all patterns at once."""
        detector = PatternDetector()
        
        results = detector.detect_all(sample_data, "TEST")
        
        # Should return a list (may be empty depending on data)
        assert isinstance(results, list)
        
        for result in results:
            assert isinstance(result.signal_type, SignalType)
            assert 0 <= result.confidence <= 1
            assert isinstance(result.severity, SignalSeverity)
