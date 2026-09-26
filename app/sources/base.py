from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models import Watch


class SourceUnavailableError(RuntimeError):
    """A source is temporarily unreachable (WAF, rate limit, maintenance, etc.)."""


@dataclass(slots=True)
class AuctionItem:
    source: str
    external_id: str
    title: str
    url: str
    price: float | None
    currency: str | None
    image_url: str | None = None
    end_time: datetime | None = None
    start_time: datetime | None = None
    bid_count: int | None = None
    condition: str | None = None
    seller: str | None = None
    auction_type: str | None = None
    timing_text: str | None = None
    price_label: str | None = None
    estimate_text: str | None = None


class AuctionSource(Protocol):
    async def search(self, watch: Watch) -> list[AuctionItem]: ...
