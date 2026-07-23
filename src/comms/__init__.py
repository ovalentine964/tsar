"""
TSAR Communications — CloudEvents-based inter-agent messaging.

All inter-agent messages use CNCF CloudEvents v1.0 with MessagePack payload.
Transport: Redis Streams with tsar:stream:* prefix.

Components:
  - Events:    CloudEvents envelope creation and validation
  - Publisher: Publish events to Redis streams
  - Subscriber: Subscribe to Redis streams with consumer groups
"""

from src.comms.events import CloudEvent, create_event, decode_event, encode_event
from src.comms.publisher import EventPublisher, InMemoryBus
from src.comms.subscriber import EventSubscriber

__all__: list[str] = [
    "CloudEvent",
    "EventPublisher",
    "EventSubscriber",
    "InMemoryBus",
    "create_event",
    "decode_event",
    "encode_event",
]
