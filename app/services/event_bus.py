"""
Property Event Bus — pub/sub backbone for the Autonomous Property Manager.

Rules:
  • publish() MUST use asyncio.create_task() — never await handlers directly.
  • Handlers receive a PropertyEvent; they are async coroutines.
  • Module-level singleton `event_bus` is imported by other services.
  • '*' wildcard subscription receives ALL events.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class PropertyEvent:
    event_type: str
    owner_id: str          # UUID string of the property owner
    payload: Dict[str, Any]
    occurred_at: datetime = field(default_factory=datetime.utcnow)
    source: str = "system"


Handler = Callable[[PropertyEvent], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async pub/sub bus backed by asyncio tasks."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Handler]] = {}

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register *handler* for *event_type*.  Use '*' for all events."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug(f"[event_bus] Subscribed {handler.__name__} to '{event_type}'")

    def publish(self, event: PropertyEvent) -> None:
        """
        Dispatch *event* to all matching handlers using asyncio.create_task().
        This is fire-and-forget — callers must NOT await this method.
        """
        handlers: List[Handler] = []

        # Exact event type match
        if event.event_type in self._handlers:
            handlers.extend(self._handlers[event.event_type])

        # Wildcard subscribers
        if "*" in self._handlers:
            handlers.extend(self._handlers["*"])

        if not handlers:
            logger.debug(f"[event_bus] No handlers for event '{event.event_type}'")
            return

        logger.info(
            f"[event_bus] Publishing '{event.event_type}' "
            f"(owner={event.owner_id}) to {len(handlers)} handler(s)"
        )

        for handler in handlers:
            try:
                asyncio.create_task(_safe_handle(handler, event))
            except RuntimeError:
                # No running event loop (e.g. during unit tests) — run sync
                logger.warning(
                    f"[event_bus] No running loop — skipping handler {handler.__name__}"
                )


async def _safe_handle(handler: Handler, event: PropertyEvent) -> None:
    """Wrap each handler call so one failure doesn't kill the bus."""
    try:
        await handler(event)
    except Exception as exc:
        logger.error(
            f"[event_bus] Handler {handler.__name__} failed for "
            f"'{event.event_type}': {exc}",
            exc_info=True,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
event_bus = EventBus()
