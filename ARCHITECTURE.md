# CogniFlow Architecture

This document describes the architecture and design decisions of CogniFlow.

## System Overview

CogniFlow is a modular, event-driven financial proactive agent designed to:

1. **Continuously monitor** market data for meaningful patterns
2. **Generate personalized** trading intents based on detected patterns
3. **Manage context** hierarchically to provide relevant information
4. **Learn from user behavior** to improve recommendations

## Design Principles

### 1. Event-Driven Architecture

The system uses Redis Pub/Sub for asynchronous communication between modules:

```
Perception Module ──▶ Redis (market_signals) ──▶ Intent Prediction Module
                                                        │
                                                        ▼
                              Redis (user_intents) ──▶ Context Management
```

Benefits:
- Loose coupling between modules
- Easy to scale individual components
- Fault tolerance (modules can restart independently)

### 2. Modular Design

Each module is self-contained with clear interfaces:

| Module | Responsibility | Input | Output |
|--------|---------------|-------|--------|
| Perception | Pattern detection | Market data | Market signals |
| Intent Prediction | Intent generation | Signals + User context | Candidate intents |
| Context Management | Memory & profiling | User interactions | Relevant context |

### 3. Hierarchical Memory

Implements Context-Folding (from COMPASS architecture):

```
┌─────────────────────────────────────────┐
│           WORKING MEMORY                │  ~4K tokens, 4 hours
│  Recent signals, active conversations   │
└─────────────────────────────────────────┘
                    │
                    ▼ (when full, fold to)
┌─────────────────────────────────────────┐
│         SHORT-TERM MEMORY               │  ~16K tokens, 7 days
│  Daily summaries, folded working mem    │
└─────────────────────────────────────────┘
                    │
                    ▼ (when full, fold to)
┌─────────────────────────────────────────┐
│          LONG-TERM MEMORY               │  ~64K tokens, 1 year
│  Weekly summaries, folded short-term    │
└─────────────────────────────────────────┘
```

## Module Details

### Perception Module

**Components:**
- `PatternDetector`: Rule-based pattern detection
- `MarketMonitor`: Continuous monitoring loop
- `FMPClient`: Financial Modeling Prep API client

**Detection Algorithms:**

1. **Price Anomaly**
   - Uses Bollinger Bands (Z-score > threshold)
   - Detects overbought/oversold conditions
   - Severity based on deviation magnitude

2. **Volume Spike**
   - Compares current volume to 20-day average
   - Threshold: 2x average by default
   - Indicates increased market interest

3. **Volatility Change**
   - Uses ATR (Average True Range)
   - Detects significant volatility shifts
   - 50% change threshold by default

4. **MA Cross**
   - Golden cross (MA20 > MA50): Bullish
   - Death cross (MA20 < MA50): Bearish
   - Must cross from opposite direction

5. **Support/Resistance Touch**
   - Identifies key levels from recent highs/lows
   - Triggers when price within 1% of level
   - Considered with volume confirmation

### Intent Prediction Module

**Intent Types:**

| Intent | Description | Trigger |
|--------|-------------|---------|
| BUY_DIP | Buy on price weakness | Price below BB lower |
| TAKE_PROFIT | Realize gains | Price above BB upper + profit |
| STOP_PROFIT_LOSS | Protect position | Price near support with loss |
| REBALANCE | Adjust allocation | Portfolio drift |
| REDUCE_RISK | Decrease exposure | High volatility |
| HOLD_WAIT | Maintain position | Uncertain direction |
| INFO_SEEKING | Research needed | Volume spike without news |
| ADD_POSITION | Increase holding | Golden cross confirmation |
| DIVERSIFY | Spread risk | High concentration |
| REVIEW_STOPS | Check stop levels | Death cross |

**Evaluation Dimensions:**

1. **Relevance** (25%): Match to user's portfolio and preferences
2. **Urgency** (20%): Time-sensitivity of opportunity
3. **Information Gap** (15%): Need for additional research
4. **Consistency** (15%): Alignment with recent user actions
5. **Risk Assessment** (25%): Suitability for risk profile

### Context Management Module

**Memory Operations:**

```python
# Store entry
await memory.add_entry(
    user_id=1,
    tier=MemoryTier.WORKING,
    context_type=ContextType.MARKET_PATTERN,
    content="AAPL broke resistance at $175",
    importance=0.8,
)

# Query relevant context
context = await memory.query_relevant(
    user_id=1,
    query="What happened with AAPL?",
    max_tokens=2000,
)
```

**Context-Folding Process:**

1. Monitor tier token usage
2. When usage > 90%, trigger folding
3. Select lowest importance + oldest entries
4. Generate summary using rule-based or LLM
5. Store summary as folded entry
6. Mark original entries as folded

Token savings: 30-70% depending on content redundancy.

## Data Flow

### Signal Detection Flow

```
1. Market Data (FMP API)
         │
         ▼
2. Technical Indicators (TA-Lib)
         │
         ▼
3. Pattern Detection (5 algorithms)
         │
         ▼
4. Signal Persistence (PostgreSQL)
         │
         ▼
5. Redis Publish (market_signals)
```

### Intent Generation Flow

```
1. Redis Subscribe (market_signals)
         │
         ▼
2. Intent Template Matching
         │
         ▼
3. Candidate Generation (rule-based)
         │
         ▼
4. Multi-Dimension Evaluation
         │
         ▼
5. Intent Persistence (PostgreSQL)
         │
         ▼
6. Redis Publish (user_intents)
```

### Context Retrieval Flow

```
1. Query Input
         │
         ▼
2. Tier Selection (Working → Short-term → Long-term)
         │
         ▼
3. Entry Retrieval (by relevance/importance)
         │
         ▼
4. Token Budget Check
         │
         ▼
5. Context Assembly
         │
         ▼
6. Response with context
```

## Database Schema

### Core Tables

```sql
-- Market signals from pattern detection
market_signals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    signal_type VARCHAR(50),      -- PRICE_ANOMALY, VOLUME_SPIKE, etc.
    severity VARCHAR(20),          -- LOW, MEDIUM, HIGH, CRITICAL
    symbol VARCHAR(20),
    confidence FLOAT,              -- 0-1
    price_at_signal FLOAT,
    indicators_snapshot JSONB,     -- Technical indicators at detection
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE
)

-- Generated trading intents
user_intents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    intent_type VARCHAR(50),       -- BUY_DIP, TAKE_PROFIT, etc.
    status VARCHAR(20),            -- PENDING, ACCEPTED, REJECTED, etc.
    confidence FLOAT,
    urgency FLOAT,
    priority_score FLOAT,
    trigger_signal_ids INTEGER[],
    target_symbol VARCHAR(20),
    proposed_action JSONB,
    evaluation_scores JSONB,
    evaluation_reasoning TEXT,
    created_at TIMESTAMP,
    expires_at TIMESTAMP
)

-- Hierarchical memory entries
memory_entries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    tier VARCHAR(20),              -- WORKING, SHORT_TERM, LONG_TERM
    context_type VARCHAR(50),      -- MARKET_PATTERN, INTENT_HISTORY, etc.
    content TEXT,
    token_count INTEGER,
    importance_score FLOAT,        -- 0-1
    is_folded BOOLEAN DEFAULT FALSE,
    folded_from_entries INTEGER[],
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    last_accessed_at TIMESTAMP
)

-- User behavior profile
user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    preferred_intent_types VARCHAR[],
    disliked_intent_types VARCHAR[],
    preferred_symbols VARCHAR[],
    notification_frequency VARCHAR,
    preferred_contact_method VARCHAR,
    quiet_hours_start INTEGER,
    quiet_hours_end INTEGER,
    average_response_time_minutes FLOAT,
    acceptance_rate FLOAT
)
```

## Scaling Considerations

### Horizontal Scaling

- **Perception Module**: Can run multiple instances, each handling subset of symbols
- **Intent Prediction**: Stateless, can scale horizontally
- **Context Management**: User-scoped, can shard by user_id

### Performance Optimizations

1. **Database**: Index on (user_id, created_at) for time-series queries
2. **Redis**: Connection pooling, pipeline for batch operations
3. **Memory**: LRU cache for frequently accessed user profiles
4. **Detection**: Pre-computed indicators, incremental updates

### Future Enhancements

1. **ML-based Detection**: Train models on labeled patterns
2. **Real-time Streaming**: WebSocket for live price updates
3. **Multi-asset**: Extend to crypto, forex, commodities
4. **Backtesting**: Historical simulation framework

## Security Considerations

1. **API Keys**: Store in environment variables, rotate regularly
2. **Database**: Use connection pooling with SSL
3. **Redis**: Enable AUTH, use TLS in production
4. **PII**: Encrypt sensitive user data at rest
5. **Rate Limiting**: Implement per-user rate limits on API
