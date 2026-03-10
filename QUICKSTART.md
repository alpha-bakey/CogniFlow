# CogniFlow Quick Start

Get started with CogniFlow in 5 minutes.

## Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Redis 7+
- (Optional) Docker & Docker Compose

## Installation

### Option 1: Using Docker (Recommended)

```bash
# Clone repository
cd CogniFlow

# Start services
docker-compose up -d postgres redis

# Install dependencies
pip install -e ".[dev]"

# Initialize database
make migrate

# Run demo
make demo
```

### Option 2: Manual Setup

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Setup PostgreSQL
createdb cogniflow

# 3. Setup Redis
redis-server

# 4. Configure environment
cp .env.example .env
# Edit .env with your settings

# 5. Initialize database
python -c "from cogniflow.models.database import init_db; import asyncio; asyncio.run(init_db())"
```

## Running the Demo

```bash
# Using make
make demo

# Or directly
PYTHONPATH=./src python examples/demo.py
```

Expected output:
```
============================================================
  COGNIFLOW FINANCIAL AGENT - DEMO
============================================================

DEMO 1: PERCEPTION MODULE
...
DEMO 2: INTENT PREDICTION MODULE
...
DEMO 3: CONTEXT MANAGEMENT MODULE
...
```

## Running the API Server

```bash
# Using make
make server

# Or directly
PYTHONPATH=./src uvicorn cogniflow.server:app --reload
```

API will be available at: http://localhost:8000

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/analyze/{symbol}` | POST | Analyze a stock symbol |
| `/signals/{user_id}` | GET | Get user's market signals |
| `/intents/{user_id}` | GET | Get user's trading intents |
| `/context/{user_id}/query` | POST | Query user context |

### Example API Call

```bash
# Analyze AAPL
curl http://localhost:8000/analyze/AAPL

# Response
{
  "symbol": "AAPL",
  "patterns_detected": 2,
  "signals": [
    {
      "type": "PRICE_ANOMALY",
      "severity": "HIGH",
      "confidence": 0.85,
      "description": "Price above upper Bollinger Band"
    }
  ]
}
```

## Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test
pytest tests/test_perception.py -v
```

## Project Structure

```
CogniFlow/
├── src/cogniflow/
│   ├── core/
│   │   ├── perception/        # Pattern detection
│   │   ├── intent/            # Intent generation
│   │   └── context/           # Memory management
│   ├── models/
│   │   └── database.py        # SQLAlchemy models
│   ├── config.py              # Settings
│   └── server.py              # FastAPI app
├── tests/                     # Test suite
├── examples/
│   └── demo.py               # Demo script
├── docker-compose.yml         # Docker services
└── README.md                  # Full documentation
```

## Configuration

Key environment variables (see `.env.example`):

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/cogniflow

# Redis
REDIS_URL=redis://localhost:6379/0

# Market Data
FMP_API_KEY=your_fmp_api_key

# Module Settings
PERCEPTION_MONITORING_INTERVAL=60
INTENT_MIN_CONFIDENCE=0.6
```

## Next Steps

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design
2. Explore the API at http://localhost:8000/docs
3. Customize pattern detection thresholds in `config.py`
4. Add your own intent templates in `intent/generator.py`

## Troubleshooting

**ImportError: No module named 'cogniflow'**
```bash
export PYTHONPATH=./src:$PYTHONPATH
```

**Database connection failed**
```bash
# Check PostgreSQL is running
docker-compose ps

# Or create database manually
createdb cogniflow
```

**Redis connection failed**
```bash
# Check Redis is running
docker-compose ps redis

# Or start Redis locally
redis-server
```

## Support

- Issues: https://github.com/cogniflow/financial-agent/issues
- Docs: See `README.md` and `ARCHITECTURE.md`
