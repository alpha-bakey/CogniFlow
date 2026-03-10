# CogniFlow 🧠📈

**Financial Proactive Agent** - An intelligent, event-driven system for proactive financial analysis and personalized trading intent generation.

## Overview

CogniFlow is a modular AI system that continuously monitors financial markets, detects meaningful patterns, and generates actionable trading intents tailored to individual users. It combines real-time market data analysis with personalized context management to deliver timely, relevant financial insights.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         COGNIFLOW                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  PERCEPTION  │───▶│    INTENT    │───▶│    CONTEXT   │      │
│  │    MODULE    │    │ PREDICTION   │    │ MANAGEMENT   │      │
│  │              │    │   MODULE     │    │   MODULE     │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │                │
│         ▼                   ▼                   ▼                │
│    ┌──────────────────────────────────────────────────────┐     │
│    │              REDIS MESSAGE QUEUE                      │     │
│    │  • market_signals  • user_intents  • system_events   │     │
│    └──────────────────────────────────────────────────────┘     │
│         │                   │                   │                │
│         ▼                   ▼                   ▼                │
│    ┌──────────────────────────────────────────────────────┐     │
│    │                 POSTGRESQL DATABASE                   │     │
│    │  • Market Signals  • User Intents  • Memory Entries  │     │
│    └──────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Modules

### 1. Perception Module 👁️

Continuously monitors market data and detects patterns:

- **Price Anomaly Detection** - Bollinger Band breaches
- **Volume Spike Detection** - Unusual trading activity  
- **Volatility Change** - ATR-based volatility shifts
- **Moving Average Crosses** - Golden/Death cross detection
- **Support/Resistance Touch** - Key level detection

```python
from cogniflow.core import PerceptionModule, PatternDetector

detector = PatternDetector(
    price_anomaly_threshold=2.5,
    volume_spike_threshold=2.0
)

module = PerceptionModule(db_session, detector=detector)
module.add_symbols(["AAPL", "MSFT", "GOOGL"])
await module.start()
```

### 2. Intent Prediction Module 🎯

Generates and evaluates trading intents:

- **10 Intent Types**: BUY_DIP, TAKE_PROFIT, STOP_PROFIT_LOSS, REBALANCE, REDUCE_RISK, HOLD_WAIT, INFO_SEEKING, ADD_POSITION, DIVERSIFY, REVIEW_STOPS
- **5-Dimension Evaluation**: Relevance, Urgency, Information Gap, Consistency, Risk Assessment
- **Personalized Scoring** - Based on user profile and portfolio

```python
from cogniflow.core import IntentPredictionModule

module = IntentPredictionModule(db_session)
await module.initialize()
await module.start()
```

### 3. Context Management Module 🧠

Hierarchical memory system with Context-Folding:

- **Three Memory Tiers**:
  - Working Memory: ~4K tokens, 4 hours
  - Short-term Memory: ~16K tokens, 7 days
  - Long-term Memory: ~64K tokens, 1 year

- **Context-Folding** - Automatically summarizes older entries to save tokens
- **User Profiling** - Learns preferences from behavior

```python
from cogniflow.core import ContextManagementModule, HierarchicalMemoryManager

# Store memory
await memory_manager.add_entry(
    user_id=1,
    tier=MemoryTier.WORKING,
    context_type=ContextType.MARKET_PATTERN,
    content="AAPL broke above resistance at $175",
    importance=0.8
)

# Query relevant context
context = await memory_manager.query_relevant(
    user_id=1,
    query="What happened with AAPL recently?",
    max_tokens=2000
)
```

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/cogniflow/financial-agent.git
cd financial-agent

# Install dependencies
pip install -e ".[dev]"

# Copy environment file
cp .env.example .env
# Edit .env with your settings
```

### Setup Database

```bash
# Start PostgreSQL and Redis
docker-compose up -d postgres redis

# Initialize database
python -c "from cogniflow.models.database import init_db; import asyncio; asyncio.run(init_db())"
```

### Run Demo

```python
import asyncio
from cogniflow.core import PerceptionModule
from cogniflow.models.database import async_session

async def main():
    async with async_session() as db:
        module = PerceptionModule(db)
        await module.initialize()
        
        # Analyze a symbol
        results = await module.analyze_symbol("AAPL")
        
        for r in results:
            print(f"Detected: {r.signal_type.value} - {r.description}")

asyncio.run(main())
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `FMP_API_KEY` | - | Financial Modeling Prep API key |
| `PRICE_ANOMALY_THRESHOLD` | 2.5 | Z-score threshold for price anomalies |
| `VOLUME_SPIKE_THRESHOLD` | 2.0 | Multiplier for volume spike detection |
| `INTENT_MIN_CONFIDENCE` | 0.6 | Minimum confidence for intent generation |
| `INTENT_MIN_OVERALL_SCORE` | 0.5 | Minimum evaluation score to recommend |

## Database Schema

### Core Tables

```sql
-- Market signals from pattern detection
CREATE TABLE market_signals (
    id SERIAL PRIMARY KEY,
    signal_type VARCHAR(50),
    severity VARCHAR(20),
    symbol VARCHAR(20),
    confidence FLOAT,
    price_at_signal FLOAT,
    indicators_snapshot JSONB,
    created_at TIMESTAMP
);

-- Generated trading intents
CREATE TABLE user_intents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    intent_type VARCHAR(50),
    status VARCHAR(20),
    confidence FLOAT,
    priority_score FLOAT,
    evaluation_scores JSONB
);

-- Hierarchical memory entries
CREATE TABLE memory_entries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    tier VARCHAR(20),
    content TEXT,
    token_count INTEGER,
    importance_score FLOAT,
    is_folded BOOLEAN DEFAULT FALSE
);
```

## API Example

```python
from fastapi import FastAPI
from cogniflow.core import PerceptionModule, IntentPredictionModule

app = FastAPI()

@app.post("/analyze/{symbol}")
async def analyze_symbol(symbol: str):
    """Analyze a symbol and return detected patterns."""
    results = await perception_module.analyze_symbol(symbol)
    return {
        "symbol": symbol,
        "patterns_detected": len(results),
        "signals": [r.to_dict() for r in results]
    }

@app.get("/intents/{user_id}")
async def get_intents(user_id: int):
    """Get pending intents for a user."""
    intents = await get_pending_intents(user_id)
    return {"intents": intents}
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=cogniflow

# Run specific module tests
pytest tests/test_perception.py
pytest tests/test_intent.py
pytest tests/test_context.py
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Roadmap

- [ ] DeepSeek R1 integration for enhanced reasoning
- [ ] Multi-asset support (crypto, forex)
- [ ] Webhook notifications
- [ ] Backtesting framework
- [ ] Model-based pattern detection (LSTM, Transformers)
