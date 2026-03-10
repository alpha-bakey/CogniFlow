"""
CogniFlow Demo Script

Demonstrates the three core modules working together:
1. Perception Module - Detect market patterns
2. Intent Prediction Module - Generate trading intents
3. Context Management Module - Store and retrieve context
"""
import asyncio
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Demo configuration
DEMO_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA"]


async def demo_perception():
    """Demo: Perception Module - Pattern Detection"""
    print("\n" + "="*60)
    print("DEMO 1: PERCEPTION MODULE")
    print("="*60)
    
    from cogniflow.core.perception import PatternDetector
    import pandas as pd
    import numpy as np
    
    # Generate sample market data
    np.random.seed(42)
    dates = pd.date_range(end=datetime.now(), periods=90, freq='D')
    
    # Simulate price with trend and volatility
    returns = np.random.normal(0.001, 0.02, 90)
    prices = 150 * np.exp(np.cumsum(returns))
    
    # Create DataFrame
    df = pd.DataFrame({
        'date': dates,
        'open': prices * (1 + np.random.normal(0, 0.005, 90)),
        'high': prices * (1 + np.abs(np.random.normal(0.01, 0.005, 90))),
        'low': prices * (1 - np.abs(np.random.normal(0.01, 0.005, 90))),
        'close': prices,
        'volume': np.random.randint(50_000_000, 100_000_000, 90),
    })
    
    # Calculate indicators
    df['ma_20'] = df['close'].rolling(20).mean()
    df['ma_50'] = df['close'].rolling(50).mean()
    df['std_20'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['ma_20'] + (df['std_20'] * 2)
    df['bb_lower'] = df['ma_20'] - (df['std_20'] * 2)
    
    # RSI calculation
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Create detector
    detector = PatternDetector(
        price_anomaly_threshold=2.0,
        volume_spike_threshold=1.5,
    )
    
    # Detect patterns
    print(f"\nAnalyzing {len(df)} days of AAPL data...\n")
    
    # Test individual detectors
    anomaly = detector.detect_price_anomaly(df, "AAPL")
    if anomaly:
        print(f"✓ Price Anomaly Detected:")
        print(f"  Type: {anomaly.signal_type.value}")
        print(f"  Severity: {anomaly.severity.value}")
        print(f"  Confidence: {anomaly.confidence:.1%}")
        print(f"  Description: {anomaly.description}")
    else:
        print("✗ No price anomaly detected")
    
    volume = detector.detect_volume_spike(df, "AAPL")
    if volume:
        print(f"\n✓ Volume Spike Detected:")
        print(f"  Confidence: {volume.confidence:.1%}")
        print(f"  Description: {volume.description}")
    else:
        print("\n✗ No volume spike detected")
    
    # Detect all patterns
    print("\n--- All Pattern Detection ---")
    all_patterns = detector.detect_all(df, "AAPL")
    print(f"Total patterns detected: {len(all_patterns)}")
    for p in all_patterns:
        print(f"  - {p.signal_type.value} ({p.severity.value}): {p.description[:60]}...")
    
    return all_patterns


async def demo_intent_prediction():
    """Demo: Intent Prediction Module"""
    print("\n" + "="*60)
    print("DEMO 2: INTENT PREDICTION MODULE")
    print("="*60)
    
    from cogniflow.core.intent import IntentGenerator, IntentEvaluator
    from cogniflow.core.intent.generator import CandidateIntent
    from cogniflow.models.database import IntentType, SignalType
    
    # Create mock signal
    class MockSignal:
        def __init__(self):
            self.id = 1
            self.signal_type = SignalType.PRICE_ANOMALY
            self.symbol = "AAPL"
            self.confidence = 0.85
            self.price_at_signal = 175.50
            self.indicators_snapshot = {
                "bb_position": "above_upper",
                "z_score": 2.8,
                "rsi": 72.5,
            }
    
    signal = MockSignal()
    
    # Create mock portfolio
    portfolio = {
        "holdings": {
            "AAPL": {
                "quantity": 100,
                "avg_cost": 150.00,
                "value": 17550.00,
            }
        },
        "cash": 10000,
        "total_value": 27550,
    }
    
    print(f"\nInput Signal:")
    print(f"  Symbol: {signal.symbol}")
    print(f"  Type: {signal.signal_type.value}")
    print(f"  Confidence: {signal.confidence:.1%}")
    print(f"  Price: ${signal.price_at_signal}")
    
    print(f"\nPortfolio:")
    print(f"  AAPL Position: {portfolio['holdings']['AAPL']['quantity']} shares")
    print(f"  Avg Cost: ${portfolio['holdings']['AAPL']['avg_cost']}")
    print(f"  Unrealized P&L: +{(175.50/150-1)*100:.1f}%")
    
    # Generate intents
    generator = IntentGenerator(min_confidence=0.6)
    candidates = await generator.generate_candidates(
        signals=[signal],
        portfolio=portfolio,
    )
    
    print(f"\n--- Generated Intents ---")
    print(f"Candidates: {len(candidates)}")
    
    for i, c in enumerate(candidates, 1):
        print(f"\n{i}. {c.intent_type.value}")
        print(f"   Confidence: {c.confidence:.1%}")
        print(f"   Urgency: {c.urgency:.1%}")
        print(f"   Priority Score: {c.priority_score:.3f}")
        print(f"   Reasoning: {c.reasoning[:80]}...")
        if c.proposed_action:
            print(f"   Proposed Action: {c.proposed_action.get('action')} "
                  f"{c.proposed_action.get('symbol', '')}")
    
    # Evaluate first candidate
    if candidates:
        print("\n--- Intent Evaluation ---")
        evaluator = IntentEvaluator()
        
        user_context = {
            "risk_profile": "moderate",
            "watchlist": ["AAPL", "MSFT"],
        }
        
        evaluation = await evaluator.evaluate(
            intent=candidates[0],
            user_context=user_context,
            portfolio=portfolio,
            recent_intents=[],
        )
        
        print(f"Intent: {evaluation.intent_type}")
        print(f"Overall Score: {evaluation.overall_score:.2f}")
        print(f"Should Recommend: {evaluation.should_recommend}")
        print(f"\nDimension Scores:")
        for dim, score in evaluation.scores.items():
            bar = "█" * int(score * 20)
            print(f"  {dim:20s}: {score:.2f} {bar}")
        
        if evaluation.risk_flags:
            print(f"\nRisk Flags: {', '.join(evaluation.risk_flags)}")
        
        print(f"\nReasoning: {evaluation.reasoning}")
    
    return candidates


async def demo_context_management():
    """Demo: Context Management Module"""
    print("\n" + "="*60)
    print("DEMO 3: CONTEXT MANAGEMENT MODULE")
    print("="*60)
    
    from cogniflow.models.database import MemoryTier, ContextType
    from cogniflow.core.context.memory_manager import TokenEstimator
    
    print("\n--- Token Estimation ---")
    
    estimator = TokenEstimator()
    
    texts = [
        "AAPL price broke above resistance at $175",
        "Volume spike detected: 3.5x average trading volume",
        "Moving average golden cross: MA20 crossed above MA50 with 2.1% divergence",
    ]
    
    for text in texts:
        tokens = estimator.estimate(text)
        print(f"Text ({tokens} tokens): {text[:50]}...")
    
    print("\n--- Memory Tier Budgets ---")
    budgets = {
        MemoryTier.WORKING: 4000,
        MemoryTier.SHORT_TERM: 16000,
        MemoryTier.LONG_TERM: 64000,
    }
    
    for tier, budget in budgets.items():
        print(f"{tier.value:12s}: {budget:6,} tokens")
    
    print("\n--- Context-Folding Simulation ---")
    
    # Simulate entries that would be folded
    entries = [
        {"time": "09:30", "content": "AAPL opened at $174.50", "importance": 0.3},
        {"time": "10:15", "content": "Volume increasing, price at $174.80", "importance": 0.4},
        {"time": "11:00", "content": "Broke resistance level at $175", "importance": 0.8},
        {"time": "12:30", "content": "Consolidating around $175.20", "importance": 0.3},
        {"time": "14:00", "content": "Volume spike detected", "importance": 0.7},
    ]
    
    print("Original entries (5):")
    total_tokens = 0
    for e in entries:
        tokens = estimator.estimate(e["content"])
        total_tokens += tokens
        print(f"  [{e['time']}] ({tokens} tokens, importance={e['importance']}) {e['content']}")
    
    print(f"\nTotal tokens: {total_tokens}")
    
    # Simulate folding
    print("\nAfter Context-Folding:")
    summary = "[Summary] AAPL trading session: Opened $174.50, broke resistance at $175 with volume spike. Current: $175.20"
    summary_tokens = estimator.estimate(summary)
    print(f"  Summary ({summary_tokens} tokens): {summary}")
    print(f"  Token reduction: {total_tokens} → {summary_tokens} ({(1 - summary_tokens/total_tokens)*100:.0f}% saved)")
    
    print("\n--- User Profiling ---")
    
    # Simulate learned preferences
    preferences = {
        "preferred_intent_types": ["BUY_DIP", "TAKE_PROFIT", "STOP_PROFIT_LOSS"],
        "preferred_symbols": ["AAPL", "MSFT", "NVDA"],
        "avg_response_time": 23.5,  # minutes
        "acceptance_rate": 0.68,
        "best_response_hours": [9, 10, 14, 15],
    }
    
    print("Learned User Profile:")
    print(f"  Preferred intents: {', '.join(preferences['preferred_intent_types'])}")
    print(f"  Watched symbols: {', '.join(preferences['preferred_symbols'])}")
    print(f"  Avg response time: {preferences['avg_response_time']:.1f} minutes")
    print(f"  Intent acceptance rate: {preferences['acceptance_rate']:.1%}")
    print(f"  Most active hours: {preferences['best_response_hours']}")


async def demo_full_pipeline():
    """Demo: Full pipeline integration"""
    print("\n" + "="*60)
    print("DEMO 4: FULL PIPELINE")
    print("="*60)
    
    print("""
┌─────────────────────────────────────────────────────────────┐
│  PIPELINE FLOW                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. MARKET DATA ──▶ 2. PATTERN DETECTION                   │
│     AAPL: $175.50      • Price above BB upper              │
│     Volume: 95M        • RSI: 72.5 (overbought)            │
│                        • Z-score: 2.8                      │
│                                    │                        │
│                                    ▼                        │
│                         3. SIGNAL GENERATED                 │
│                            ┌──────────────┐                 │
│                            │ Signal:      │                 │
│                            │ PRICE_ANOMALY│                 │
│                            │ Severity: HIGH│                │
│                            └──────┬───────┘                 │
│                                   │                         │
│                                   ▼                         │
│                         4. INTENT PREDICTION                │
│                            ┌──────────────┐                 │
│                            │ TAKE_PROFIT  │                 │
│                            │ Confidence:  │                 │
│                            │    77%       │                 │
│                            └──────┬───────┘                 │
│                                   │                         │
│                                   ▼                         │
│                         5. CONTEXT STORAGE                  │
│                            ┌──────────────┐                 │
│                            │ WORKING      │                 │
│                            │ MEMORY:      │                 │
│                            │ AAPL signal  │                 │
│                            │ recorded     │                 │
│                            └──────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
""")
    
    print("✓ Pipeline complete!")
    print("\nIn production:")
    print("  • Redis Pub/Sub distributes signals between modules")
    print("  • PostgreSQL persists all signals and intents")
    print("  • Context-Folding optimizes token usage")
    print("  • User Profiler learns from interactions")


async def main():
    """Run all demos"""
    print("\n" + "="*60)
    print("  COGNIFLOW FINANCIAL AGENT - DEMO")
    print("="*60)
    print("\nThis demo showcases the three core modules of CogniFlow:")
    print("  1. Perception Module    - Market pattern detection")
    print("  2. Intent Prediction    - Trading intent generation")
    print("  3. Context Management   - Hierarchical memory system")
    
    # Run demos
    await demo_perception()
    await demo_intent_prediction()
    await demo_context_management()
    await demo_full_pipeline()
    
    print("\n" + "="*60)
    print("  DEMO COMPLETE")
    print("="*60)
    print("\nFor production use:")
    print("  1. Set up PostgreSQL and Redis")
    print("  2. Configure API keys in .env")
    print("  3. Run: python -m cogniflow.server")
    print("\nSee README.md for full documentation.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
