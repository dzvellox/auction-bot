from __future__ import annotations

import base64
import time
from datetime import datetime
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.models import Watch
from app.sources.base import AuctionItem


class EbaySource:
    name = "ebay"
    status_label = "ebay (API officielle)"
    TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._client = httpx.AsyncClient(timeout=25.0)
        self.last_report = ""

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        basic = base64.b64encode(
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode("utf-8")
        ).decode("ascii")
        response = await self._client.post(
            self.TOKEN_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 7200))
        return self._token

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def search(self, watch: Watch) -> list[AuctionItem]:
        token = await self._get_token()

        filters = ["buyingOptions:{AUCTION}"]
        if watch.min_price is not None and watch.max_price is not None:
            filters.append(f"price:[{watch.min_price}..{watch.max_price}]")
        elif watch.min_price is not None:
            filters.append(f"price:[{watch.min_price}]")
        elif watch.max_price is not None:
            filters.append(f"price:[..{watch.max_price}]")
        if watch.min_price is not None or watch.max_price is not None:
            filters.append(f"priceCurrency:{settings.ebay_currency}")
        if watch.condition in {"NEW", "USED"}:
            filters.append(f"conditions:{{{watch.condition}}}")

        params = {
            "q": watch.query,
            "filter": ",".join(filters),
            "sort": "newlyListed",
            "limit": "50",
        }
        response = await self._client.get(
            f"{self.SEARCH_URL}?{urlencode(params)}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_id,
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()

        results: list[AuctionItem] = []
        for row in payload.get("itemSummaries", []):
            buying_options = set(row.get("buyingOptions", []))
            if "AUCTION" not in buying_options:
                continue

            price_obj = row.get("currentBidPrice") or row.get("price") or {}
            image = (row.get("image") or {}).get("imageUrl")
            results.append(
                AuctionItem(
                    source="ebay",
                    external_id=str(row.get("itemId", "")),
                    title=row.get("title") or "Annonce eBay",
                    url=row.get("itemWebUrl") or "https://www.ebay.fr/",
                    price=float(price_obj["value"]) if price_obj.get("value") else None,
                    currency=price_obj.get("currency"),
                    image_url=image,
                    end_time=self._parse_dt(row.get("itemEndDate")),
                    bid_count=row.get("bidCount"),
                    condition=row.get("condition"),
                    seller=(row.get("seller") or {}).get("username"),
                    price_label="Enchère actuelle",
                )
            )
        self.last_report = f"{len(results)} enchère(s) retournée(s) par l’API eBay"
        return results
