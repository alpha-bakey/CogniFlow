"""
Redis-based message queue for inter-module communication.
"""
import json
import logging
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime, timezone

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisMessageQueue:
    """
    Redis-based message queue for asynchronous communication between modules.
    
    Channels:
    - market_signals: Perception Module → Intent Prediction Module
    - user_intents: Intent Prediction Module → Notification/Context
    - system_events: System-wide events
    """
    
    # Channel names
    CHANNEL_MARKET_SIGNALS = "cogniflow:market_signals"
    CHANNEL_USER_INTENTS = "cogniflow:user_intents"
    CHANNEL_SYSTEM_EVENTS = "cogniflow:system_events"
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._handlers: Dict[str, List[Callable]] = {
            self.CHANNEL_MARKET_SIGNALS: [],
            self.CHANNEL_USER_INTENTS: [],
            self.CHANNEL_SYSTEM_EVENTS: [],
        }
        self._running = False
    
    async def connect(self) -> None:
        """Initialize Redis connection."""
        if self._redis is None:
            try:
                self._redis = await redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    health_check_interval=30,
                )
                logger.info(f"Connected to Redis at {self.redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Disconnected from Redis")
    
    async def publish(
        self,
        channel: str,
        message: Dict[str, Any],
    ) -> bool:
        """
        Publish a message to a channel.
        
        Args:
            channel: Channel name
            message: Message payload
            
        Returns:
            True if published successfully
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        
        try:
            envelope = {
                "data": message,
                "metadata": {
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "channel": channel,
                }
            }
            
            serialized = json.dumps(envelope, default=str)
            await self._redis.publish(channel, serialized)
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")
            return False
    
    async def subscribe(self, channel: str, handler: Callable[[Dict], None]) -> None:
        """Subscribe to a channel with a handler function."""
        if channel not in self._handlers:
            self._handlers[channel] = []
        
        self._handlers[channel].append(handler)
        logger.debug(f"Registered handler for channel: {channel}")
    
    async def start_consuming(self) -> None:
        """Start consuming messages from subscribed channels."""
        if not any(self._handlers.values()):
            logger.warning("No handlers registered")
            return
        
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        
        self._pubsub = self._redis.pubsub()
        
        channels_with_handlers = [
            ch for ch, handlers in self._handlers.items() if handlers
        ]
        
        if not channels_with_handlers:
            return
        
        await self._pubsub.subscribe(*channels_with_handlers)
        logger.info(f"Subscribed to channels: {channels_with_handlers}")
        
        self._running = True
        
        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break
                    
                if message["type"] == "message":
                    channel = message["channel"]
                    data = message["data"]
                    
                    try:
                        parsed = json.loads(data)
                        payload = parsed.get("data", parsed)
                        
                        for handler in self._handlers.get(channel, []):
                            try:
                                await handler(payload)
                            except Exception as e:
                                logger.error(f"Handler error: {e}")
                                
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode message: {e}")
                        
        except Exception as e:
            logger.error(f"Consumer error: {e}")
            raise
        finally:
            await self._pubsub.unsubscribe(*channels_with_handlers)
    
    async def stop_consuming(self) -> None:
        """Stop consuming messages."""
        self._running = False
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
            logger.info("Stopped consuming messages")
    
    # Convenience methods
    
    async def publish_market_signal(self, signal_data: Dict[str, Any]) -> bool:
        """Publish a market signal."""
        return await self.publish(self.CHANNEL_MARKET_SIGNALS, signal_data)
    
    async def publish_user_intent(self, intent_data: Dict[str, Any]) -> bool:
        """Publish a user intent."""
        return await self.publish(self.CHANNEL_USER_INTENTS, intent_data)
    
    async def on_market_signal(self, handler: Callable[[Dict], None]) -> None:
        """Subscribe to market signals."""
        await self.subscribe(self.CHANNEL_MARKET_SIGNALS, handler)
    
    async def on_user_intent(self, handler: Callable[[Dict], None]) -> None:
        """Subscribe to user intents."""
        await self.subscribe(self.CHANNEL_USER_INTENTS, handler)
