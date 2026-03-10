"""
Intent Prediction Module - Main module coordinator.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from cogniflow.config import settings
from cogniflow.core.redis_queue import RedisMessageQueue
from cogniflow.core.intent.generator import IntentGenerator, CandidateIntent
from cogniflow.core.intent.evaluator import IntentEvaluator, EvaluationResult
from cogniflow.models.database import UserIntent, MarketSignal, IntentStatus, IntentType

logger = logging.getLogger(__name__)


class IntentPredictionModule:
    """
    Intent Prediction Module - Generates and evaluates trading intents.
    
    This module:
    1. Listens for market signals from Redis
    2. Generates candidate intents
    3. Evaluates intents across multiple dimensions
    4. Persists recommended intents to database
    5. Publishes intents to Redis
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        generator: Optional[IntentGenerator] = None,
        evaluator: Optional[IntentEvaluator] = None,
        redis_url: Optional[str] = None,
    ):
        self.db = db_session
        self.generator = generator or IntentGenerator(
            min_confidence=settings.intent_min_confidence,
        )
        self.evaluator = evaluator or IntentEvaluator(
            min_overall_score=settings.intent_min_overall_score,
        )
        self._running = False
        
        # Initialize Redis queue
        self._redis = RedisMessageQueue(redis_url or settings.redis_url)
    
    async def initialize(self):
        """Initialize Redis connection and subscribe to channels."""
        try:
            await self._redis.connect()
            await self._redis.on_market_signal(self._handle_market_signal)
            logger.info("IntentPredictionModule initialized")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Continuing without Redis.")
            self._redis = None
    
    async def shutdown(self):
        """Cleanup resources."""
        self._running = False
        if self._redis:
            await self._redis.disconnect()
    
    async def start(self):
        """Start consuming messages from Redis."""
        if self._running:
            return
        
        self._running = True
        
        if self._redis:
            logger.info("IntentPredictionModule started - consuming market signals")
            await self._redis.start_consuming()
    
    async def _handle_market_signal(self, signal_data: Dict[str, Any]):
        """Handle incoming market signal from Redis."""
        try:
            signal_id = signal_data.get("signal_id")
            user_id = signal_data.get("user_id")
            
            logger.debug(f"Received market signal {signal_id}")
            
            # Fetch full signal from database
            signal = await self._get_signal(signal_id)
            if not signal:
                logger.warning(f"Signal {signal_id} not found")
                return
            
            # Mark signal as processed
            signal.processed = True
            await self.db.commit()
            
            # Get user context and portfolio
            user_context = await self._get_user_context(user_id)
            portfolio = await self._get_portfolio(user_id)
            
            # Generate candidates
            candidates = await self.generator.generate_candidates(
                signals=[signal],
                portfolio=portfolio,
                max_candidates=settings.intent_max_candidates,
            )
            
            # Evaluate and persist
            for candidate in candidates:
                recent_intents = await self._get_recent_intents(user_id)
                
                evaluation = await self.evaluator.evaluate(
                    intent=candidate,
                    user_context=user_context,
                    portfolio=portfolio,
                    recent_intents=recent_intents,
                )
                
                if evaluation.should_recommend:
                    intent_id = await self._persist_intent(
                        user_id=user_id,
                        candidate=candidate,
                        evaluation=evaluation,
                    )
                    
                    # Publish to Redis
                    if self._redis:
                        await self._redis.publish_user_intent({
                            "intent_id": intent_id,
                            "user_id": user_id,
                            "intent_type": candidate.intent_type.value,
                            "symbol": candidate.target_symbol,
                            "confidence": candidate.confidence,
                            "score": evaluation.overall_score,
                        })
                    
                    logger.info(
                        f"Generated intent: {candidate.intent_type.value} for "
                        f"{candidate.target_symbol} (score={evaluation.overall_score:.2f})"
                    )
                    
        except Exception as e:
            logger.error(f"Error handling market signal: {e}")
    
    async def process_signal_directly(
        self,
        signal: MarketSignal,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process a signal directly (without Redis).
        
        Args:
            signal: Market signal to process
            user_id: Optional user ID
            
        Returns:
            List of generated intents
        """
        # Get user context and portfolio
        user_context = await self._get_user_context(user_id)
        portfolio = await self._get_portfolio(user_id)
        
        # Generate candidates
        candidates = await self.generator.generate_candidates(
            signals=[signal],
            portfolio=portfolio,
        )
        
        results = []
        
        for candidate in candidates:
            recent_intents = await self._get_recent_intents(user_id)
            
            evaluation = await self.evaluator.evaluate(
                intent=candidate,
                user_context=user_context,
                portfolio=portfolio,
                recent_intents=recent_intents,
            )
            
            intent_id = await self._persist_intent(
                user_id=user_id,
                candidate=candidate,
                evaluation=evaluation,
            )
            
            results.append({
                "intent_id": intent_id,
                "candidate": candidate.to_dict(),
                "evaluation": evaluation.to_dict(),
            })
        
        return results
    
    async def _persist_intent(
        self,
        user_id: Optional[int],
        candidate: CandidateIntent,
        evaluation: EvaluationResult,
    ) -> int:
        """Persist intent to database."""
        intent = UserIntent(
            user_id=user_id or 0,
            intent_type=candidate.intent_type.value,
            status=IntentStatus.PENDING.value,
            confidence=candidate.confidence,
            urgency=candidate.urgency,
            priority_score=candidate.priority_score,
            trigger_signal_ids=candidate.trigger_signals,
            target_symbol=candidate.target_symbol,
            proposed_action=candidate.proposed_action,
            evaluation_scores=evaluation.scores,
            evaluation_reasoning=evaluation.reasoning,
            expires_at=datetime.now(timezone.utc) + timedelta(
                hours=settings.intent_expiration_hours
            ),
        )
        
        self.db.add(intent)
        await self.db.commit()
        await self.db.refresh(intent)
        
        return intent.id
    
    async def _get_signal(self, signal_id: int) -> Optional[MarketSignal]:
        """Fetch signal from database."""
        stmt = select(MarketSignal).where(MarketSignal.id == signal_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _get_user_context(self, user_id: Optional[int]) -> Dict[str, Any]:
        """Get user context for evaluation."""
        if not user_id:
            return self._get_default_context()
        
        # Fetch from user profile
        from cogniflow.models.database import UserProfile
        
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()
        
        if profile:
            return {
                "risk_profile": profile.risk_profile or "moderate",
                "preferred_intent_types": profile.preferred_intent_types or [],
                "preferred_symbols": profile.preferred_symbols or [],
                "quiet_hours_start": profile.quiet_hours_start,
                "quiet_hours_end": profile.quiet_hours_end,
            }
        
        return self._get_default_context()
    
    async def _get_portfolio(self, user_id: Optional[int]) -> Dict[str, Any]:
        """Get user portfolio."""
        # In production, this would fetch from portfolio service
        # For now, return empty or mock portfolio
        return {
            "holdings": {},
            "cash": 0,
            "total_value": 0,
        }
    
    async def _get_recent_intents(
        self,
        user_id: Optional[int],
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get recent intent history."""
        if not user_id:
            return []
        
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        stmt = select(UserIntent).where(
            and_(
                UserIntent.user_id == user_id,
                UserIntent.created_at >= since,
            )
        ).order_by(desc(UserIntent.created_at))
        
        result = await self.db.execute(stmt)
        intents = result.scalars().all()
        
        return [
            {
                "intent_type": i.intent_type,
                "target_symbol": i.target_symbol,
                "status": i.status,
                "created_at": i.created_at.isoformat(),
            }
            for i in intents
        ]
    
    def _get_default_context(self) -> Dict[str, Any]:
        """Get default user context."""
        return {
            "risk_profile": "moderate",
            "preferred_intent_types": [],
            "preferred_symbols": [],
        }
