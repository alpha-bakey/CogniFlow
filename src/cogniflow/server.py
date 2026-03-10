"""
CogniFlow API Server

FastAPI-based server providing REST endpoints for:
- Market analysis
- Intent management
- Context retrieval
- User profiling
"""
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cogniflow.config import settings
from cogniflow.core import PerceptionModule, IntentPredictionModule, ContextManagementModule
from cogniflow.models.database import (
    async_session, get_db, init_db,
    MarketSignal, UserIntent, MemoryEntry, MemoryTier, ContextType,
)

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)


# Pydantic models for API
class SymbolRequest(BaseModel):
    symbol: str


class AnalysisResponse(BaseModel):
    symbol: str
    patterns_detected: int
    signals: List[dict]


class IntentResponse(BaseModel):
    id: int
    intent_type: str
    status: str
    confidence: float
    target_symbol: Optional[str]
    reasoning: str


class MemoryEntryRequest(BaseModel):
    tier: str
    context_type: str
    content: str
    importance: float = 0.5


class ContextQueryRequest(BaseModel):
    query: str
    max_tokens: int = 4000


# Global module instances
perception_module: Optional[PerceptionModule] = None
intent_module: Optional[IntentPredictionModule] = None
context_module: Optional[ContextManagementModule] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting CogniFlow server...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down CogniFlow server...")


app = FastAPI(
    title="CogniFlow API",
    description="Financial Proactive Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


# Perception Module endpoints
@app.post("/analyze/{symbol}", response_model=AnalysisResponse)
async def analyze_symbol(
    symbol: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze a symbol and detect patterns.
    
    Args:
        symbol: Stock symbol to analyze
        
    Returns:
        Detected patterns and signals
    """
    module = PerceptionModule(db)
    
    try:
        results = await module.analyze_symbol(symbol)
        
        return AnalysisResponse(
            symbol=symbol.upper(),
            patterns_detected=len(results),
            signals=[
                {
                    "type": r.signal_type.value,
                    "severity": r.severity.value,
                    "confidence": r.confidence,
                    "description": r.description,
                    "indicators": r.indicators,
                }
                for r in results
            ],
        )
    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals/{user_id}")
async def get_signals(
    user_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Get recent signals for a user."""
    from sqlalchemy import select, desc
    
    stmt = (
        select(MarketSignal)
        .where(MarketSignal.user_id == user_id)
        .order_by(desc(MarketSignal.created_at))
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    signals = result.scalars().all()
    
    return {
        "signals": [
            {
                "id": s.id,
                "type": s.signal_type,
                "symbol": s.symbol,
                "severity": s.severity,
                "confidence": s.confidence,
                "created_at": s.created_at.isoformat(),
            }
            for s in signals
        ]
    }


# Intent Module endpoints
@app.get("/intents/{user_id}")
async def get_intents(
    user_id: int,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get intents for a user."""
    from sqlalchemy import select, desc, and_
    
    conditions = [UserIntent.user_id == user_id]
    if status:
        conditions.append(UserIntent.status == status)
    
    stmt = (
        select(UserIntent)
        .where(and_(*conditions))
        .order_by(desc(UserIntent.created_at))
    )
    
    result = await db.execute(stmt)
    intents = result.scalars().all()
    
    return {
        "intents": [
            {
                "id": i.id,
                "intent_type": i.intent_type,
                "status": i.status,
                "confidence": i.confidence,
                "target_symbol": i.target_symbol,
                "reasoning": i.evaluation_reasoning,
                "created_at": i.created_at.isoformat(),
            }
            for i in intents
        ]
    }


@app.post("/intents/{intent_id}/accept")
async def accept_intent(
    intent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Accept an intent."""
    intent = await db.get(UserIntent, intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    
    intent.status = "ACCEPTED"
    await db.commit()
    
    return {"status": "accepted", "intent_id": intent_id}


@app.post("/intents/{intent_id}/reject")
async def reject_intent(
    intent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Reject an intent."""
    intent = await db.get(UserIntent, intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    
    intent.status = "REJECTED"
    await db.commit()
    
    return {"status": "rejected", "intent_id": intent_id}


# Context Module endpoints
@app.post("/context/{user_id}/store")
async def store_context(
    user_id: int,
    request: MemoryEntryRequest,
    db: AsyncSession = Depends(get_db),
):
    """Store a memory entry."""
    from cogniflow.core.context import HierarchicalMemoryManager
    
    manager = HierarchicalMemoryManager(db)
    
    try:
        entry = await manager.add_entry(
            user_id=user_id,
            tier=MemoryTier(request.tier),
            context_type=ContextType(request.context_type),
            content=request.content,
            importance=request.importance,
        )
        
        return {
            "id": entry.id,
            "tier": entry.tier,
            "tokens": entry.token_count,
            "created_at": entry.created_at.isoformat(),
        }
    except Exception as e:
        logger.error(f"Context storage error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/context/{user_id}/query")
async def query_context(
    user_id: int,
    request: ContextQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """Query relevant context."""
    from cogniflow.core.context import HierarchicalMemoryManager
    
    manager = HierarchicalMemoryManager(db)
    
    try:
        context = await manager.query_relevant(
            user_id=user_id,
            query=request.query,
            max_tokens=request.max_tokens,
        )
        
        return {
            "context": context,
            "query": request.query,
        }
    except Exception as e:
        logger.error(f"Context query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/context/{user_id}/stats")
async def get_context_stats(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get memory usage statistics."""
    from cogniflow.core.context import HierarchicalMemoryManager
    
    manager = HierarchicalMemoryManager(db)
    stats = await manager.get_stats(user_id)
    
    return {"stats": stats}


# Run server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
