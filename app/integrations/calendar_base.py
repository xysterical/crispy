from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CalendarScheduleData:
    """Provider-agnostic schedule payload for push/pull operations."""

    title: str
    scheduled_date: str  # "YYYY-MM-DD"
    channel: str
    state: str = "draft"
    scheduled_time: str | None = None  # "HH:MM"
    notes: str | None = None
    crispy_variant_url: str | None = None
    external_id: str | None = None  # provider-side id for updates
    extra: dict = field(default_factory=dict)


class BaseCalendarProvider(ABC):
    """Push schedule data to external calendar / project-management systems.

    Separate from BaseIntegrationProvider because the data direction is
    reversed: Crispy is the source of truth pushing *out*, whereas Shopify /
    Meta providers pull data *in*.
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    async def test_connection(self) -> bool: ...

    @abstractmethod
    async def push_schedule(self, data: CalendarScheduleData) -> str:
        """Create a schedule entry in the external system.

        Returns the external system's identifier for the created entry.
        """
        ...

    @abstractmethod
    async def update_schedule(self, external_id: str, data: CalendarScheduleData) -> None: ...

    @abstractmethod
    async def delete_schedule(self, external_id: str) -> None: ...

    async def pull_schedules(self, since: str | None = None) -> list[CalendarScheduleData]:
        """Pull schedules from the external system (reserved for bidirectional sync)."""
        return []

    async def close(self) -> None:
        pass
