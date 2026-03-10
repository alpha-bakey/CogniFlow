"""
CogniFlow Agent - Main orchestrator for the proactive agent system.
"""
import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from cogniflow.modules.perception import PerceptionModule, PatternDetector
from cogniflow.modules.intent import IntentPredictionModule, IntentGenerator, IntentEvaluator
from cogniflow.modules.context import ContextManagementModule
from cogniflow.core.redis_queue import RedisMessageQueue
from cogniflow.config import settings

logger = logging.getLogger(__name__)


class CogniFlowAgent:
    """
    Main orchestrator for the CogniFlow proactive agent system.
    
    Coordinates three core modules:
    - Perception Module: Market monitoring and pattern detection
    - Intent Prediction Module: Intent generation and evaluation
    - Context Management Module: Hierarchical memory and user profiling
    """
    
    def __init__(
        self,
        db_url: Optional[str] = None,
        redis_url: Optional[str] = None,
        monitoring_interval: int = 60,
    ):
        self.db_url = db_url or settings.database_url
        self.redis_url = redis_url or settings.redis_url
        self.monitoring_interval = monitoring_interval
        
        # Database
        self._engine = None
        self._session_factory = None
        
        # Modules
        self.perception: Optional[PerceptionModule] = None
        self.intent_prediction: Optional[IntentPredictionModule] = None
        self.context: Optional[ContextManagementModule] = None
        self.redis_queue: Optional[RedisMessageQueue] = None
        
        # State
        self._running = False
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize all components."""
        if self._initialized:
            return
        
        logger.info("Initializing CogniFlow Agent...")
        
        # Initialize database
        self._engine = create_async_engine(self.db_url, echo=settings.debug)
        self._session_factory = async_sessionmaker(
            self._engine, 
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        async with self._session_factory() as session:
            # Initialize Redis
            self.redis_queue = RedisMessageQueue(self.redis_url)
            await self.redis_queue.connect()
            
            # Initialize modules
            self.perception = PerceptionModule(
                db_session=session,
                detector=PatternDetector(),
                monitoring_interval=self.monitoring_interval,
                redis_queue=self.redis_queue,
            )
            
            self.intent_prediction = IntentPredictionModule(
                db_session=session,
                generator=IntentGenerator(),
                evaluator=IntentEvaluator(),
                redis_queue=self.redis_queue,
            )
            
            self.context = ContextManagementModule(
                db_session=session,
            )
            
            # Set up cross-module communication
            await self._setup_communication()
        
        self._initialized = True
        logger.info("CogniFlow Agent initialized successfully")
    
    async def _setup_communication(self) -> None:
        """Set up inter-module communication via Redis."""
        # Perception -> Intent Prediction
        await self.redis_queue.on_market_signal(
            self._handle_market_signal
        )
        
        # Intent Prediction -> Context
        await self.redis_queue.on_user_intent(
            self._handle_user_intent
        )
    
    async def _handle_market_signal(self, signal_data: dict) -> None:
        """Handle market signal from Perception Module."""
        logger.debug(f"Received market signal: {signal_data}")
        
        if self.intent_prediction:
            await self.intent_prediction.process_signal_from_redis(signal_data)
    
    async def _handle_user_intent(self, intent_data: dict) -> None:
        """Handle user intent from Intent Prediction Module."""
        logger.debug(f"Received user intent: {intent_data}")
        
        # Track in context management
        if self.context:
            await self.context.track_intent_generation(intent_data)
    
    async def start(self) -> None:
        """Start the agent."""
        if not self._initialized:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        
        if self._running:
            logger.warning("Agent already running")
            return
        
        self._running = True
        logger.info("Starting CogniFlow Agent...")
        
        # Start Redis consumer
        if self.redis_queue:
            asyncio.create_task(self.redis_queue.start_consuming())
        
        # Start perception monitoring
        if self.perception:
            await self.perception.start_monitoring()
        
        logger.info("CogniFlow Agent started successfully")
    
    async def stop(self) -> None:
        """Stop the agent."""
        if not self._running:
            return
        
        self._running = False
        logger.info("Stopping CogniFlow Agent...")
        
        if self.perception:
            await self.perception.stop_monitoring()
        
        if self.redis_queue:
            await self.redis_queue.stop_consuming()
            await self.redis_queue.disconnect()
        
        if self._engine:
            await self._engine.dispose()
        
        logger.info("CogniFlow Agent stopped")
    
    async def run_forever(self) -> None:
        """Run the agent until interrupted."""
        await self.start()
        
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Received shutdown signal")
        finally:
            await self.stop()
