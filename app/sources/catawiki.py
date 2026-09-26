from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import quote_plus, unquote, urljoin

from bs4 import BeautifulSoup, Tag

from app.config import settings
from app.models import Watch
from app.sources.base import AuctionItem, SourceUnavailableError
from app.sources.web_common import PublicWebSource, clean_text, labelled_price, price_matches, stable_id, text_matches_query

log = logging.getLogger(__name__)
LOT_URL_RE = re.compile(r"https?://(?:www\.)?catawiki\.com/(?:[a-z]{2}/)?l/(\d+)-", re.I)
REL_LOT_RE = re.compile(r"/(?:[a-z]{2}/)?l/(\d+)-", re.I)


class CatawikiSource(PublicWebSource):
    name = "catawiki"
    base_url = "https://www.catawiki.com"

    @property
    def status_label(self) -> str:
        return "catawiki (prix détaillé)"

    def search_urls(self, query: str) -> list[str]:
        q = quote_plus(query)
        return [f"{self.base_url}/fr/s?q={q}", f"{self.base_url}/en/s?q={q}"]

    def is_result_url(self, href: str) -> bool:
        return bool(LOT_URL_RE.search(href))

    @staticmethod
    def _title_from_anchor(anchor: Tag, abs_url: str) -> str:
        for attr in ("aria-label", "title"):
            value = clean_text(str(anchor.get(attr) or ""))
            if value:
                return value
        text = clean_text(anchor.get_text(" ", strip=True))
        if text:
            return text
        img = anchor.find("img")
        if isinstance(img, Tag):
            alt = clean_text(str(img.get("alt") or ""))
            if alt:
                return alt
        slug = abs_url.split("/l/", 1)[-1]
        slug = re.sub(r"^\d+-", "", slug).split("?", 1)[0]
        return clean_text(unquote(slug).replace("-", " ")) or "Lot Catawiki"

    def _extract_candidates(self, html: str, final_url: str, watch: Watch) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=REL_LOT_RE):
            if not isinstance(anchor, Tag):
                continue
            href = str(anchor.get("href") or "").strip()
            abs_url = urljoin(final_url, href).split("#", 1)[0]
            if abs_url in seen or not self.is_result_url(abs_url):
                continue
            title = self._title_from_anchor(anchor, abs_url)
            # Search pages may wrap title in nested spans/images. Use a small
            # card context too, but never the whole page.
            context = title
            parent = anchor.parent
            for _ in range(3):
                if not isinstance(parent, Tag):
                    break
                text = clean_text(parent.get_text(" ", strip=True))
                if 0 < len(text) < 1200:
                    context = f"{context} {text}"
                parent = parent.parent
            if not text_matches_query(context, watch.query):
                continue
            seen.add(abs_url)
            out.append((abs_url, title[:500]))
        return out

    @staticmethod
    def _json_current_price(soup: BeautifulSoup) -> tuple[float | None, str | None]:
        # Catawiki changes frontend markup fairly often. Search embedded JSON for
        # *explicitly named current-bid keys* only; do not use generic estimate.
        keys = {"currentbid", "currentbidamount", "current_bid", "current_bid_amount", "bidamount", "bid_amount"}

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = re.sub(r"[^a-z_]", "", str(key).casefold())
                    if normalized in keys:
                        if isinstance(child, dict):
                            raw = child.get("amount") or child.get("value")
                            cur = child.get("currency") or child.get("currencyCode")
                        else:
                            raw = child
                            cur = None
                        try:
                            if raw is not None:
                                return float(str(raw).replace(",", ".")), cur or "EUR"
                        except ValueError:
                            pass
                    found = walk(child)
                    if found[0] is not None:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = walk(child)
                    if found[0] is not None:
                        return found
            return None, None

        for script in soup.find_all("script"):
            raw = script.string or script.get_text("", strip=False)
            raw = raw.strip() if raw else ""
            if not raw or raw[0] not in "[{":
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            price, currency = walk(data)
            if price is not None:
                return price, currency
        return None, None

    def _parse_detail(self, html: str, url: str, fallback_title: str, watch: Watch) -> AuctionItem | None:
        soup = BeautifulSoup(html, "html.parser")
        page_text = clean_text(soup.get_text(" ", strip=True))
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True)) if isinstance(h1, Tag) else fallback_title
        if not title:
            title = fallback_title
        if not text_matches_query(f"{title} {page_text[:4000]}", watch.query):
            return None

        price, currency, _ = labelled_price(
            page_text,
            ("Offre actuelle", "Current bid", "Huidig bod", "Oferta actual", "Offerta attuale"),
            window=180,
        )
        if price is None:
            price, currency = self._json_current_price(soup)
        if not price_matches(watch, price):
            return None

        timing_text = None
        # Server-rendered detail pages expose a countdown as separate words.
        countdown_patterns = [
            r"(\d{1,3})\s+jours?\s+(\d{1,2})\s+heures?\s+(\d{1,2})\s+minutes?",
            r"(\d{1,3})\s+days?\s+(\d{1,2})\s+hours?\s+(\d{1,2})\s+minutes?",
            r"(\d{1,2})\s+heures?\s+(\d{1,2})\s+minutes?",
        ]
        for pattern in countdown_patterns:
            m = re.search(pattern, page_text, re.I)
            if m:
                nums = [int(x) for x in m.groups()]
                if len(nums) == 3:
                    timing_text = f"{nums[0]} j {nums[1]} h {nums[2]} min"
                else:
                    timing_text = f"{nums[0]} h {nums[1]} min"
                break

        condition = None
        m = re.search(r"\bCondition\s+(.{1,80}?)(?=\s+(?:En état de marche|Emballage|Vendu par|Seller|$))", page_text, re.I)
        if m:
            condition = clean_text(m.group(1))[:120]

        m = LOT_URL_RE.search(url)
        external_id = m.group(1) if m else stable_id(self.name, url, title)
        return AuctionItem(
            source=self.name,
            external_id=external_id,
            title=title[:500],
            url=url,
            price=price,
            currency=currency or "EUR",
            auction_type="Chrono",
            timing_text=timing_text,
            condition=condition,
            price_label="Offre actuelle" if price is not None else None,
        )

    async def _detail_item(self, url: str, title: str, watch: Watch) -> AuctionItem | None:
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                item = self._parse_detail(response.text, str(response.url), title, watch)
                if item is not None:
                    return item
            elif response.status_code not in (401, 403, 429):
                response.raise_for_status()
        except Exception as exc:
            log.debug("catawiki detail HTTP failed %s: %s", url, exc)

        if settings.enable_browser_fallback:
            try:
                html, final_url = await self._browser_fetch(url, wait_ms=500)
                return self._parse_detail(html, final_url, title, watch)
            except Exception as exc:
                log.debug("catawiki detail browser failed %s: %s", url, exc)
        # Keep the lot if we found it but could not enrich its price. This is
        # preferable to silently dropping a valid auction.
        if price_matches(watch, None):
            m = LOT_URL_RE.search(url)
            return AuctionItem(
                source=self.name,
                external_id=m.group(1) if m else stable_id(self.name, url, title),
                title=title,
                url=url,
                price=None,
                currency="EUR",
                auction_type="Chrono",
                price_label=None,
            )
        return None

    async def search(self, watch: Watch) -> list[AuctionItem]:
        candidates: list[tuple[str, str]] = []
        errors: list[str] = []
        used_browser = False

        for url in self.search_urls(watch.query):
            try:
                response = await self.client.get(url)
                if response.status_code in (401, 403, 429):
                    errors.append(f"HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                candidates = self._extract_candidates(response.text, str(response.url), watch)
                if candidates:
                    break
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        if not candidates and settings.enable_browser_fallback:
            for url in self.search_urls(watch.query):
                try:
                    html, final_url = await self._browser_fetch(url)
                    used_browser = True
                    candidates = self._extract_candidates(html, final_url, watch)
                    if candidates:
                        break
                except SourceUnavailableError:
                    raise
                except Exception as exc:
                    errors.append(f"browser {type(exc).__name__}: {exc}")

        if not candidates:
            self.last_report = "0 lot trouvé sur la page de recherche"
            if errors:
                log.info("catawiki: %s", "; ".join(errors[:3]))
            return []

        candidates = candidates[: max(1, settings.catawiki_max_results)]
        sem = asyncio.Semaphore(max(1, settings.catawiki_detail_concurrency))

        async def enrich(pair: tuple[str, str]) -> AuctionItem | None:
            async with sem:
                return await self._detail_item(pair[0], pair[1], watch)

        items = [x for x in await asyncio.gather(*(enrich(p) for p in candidates)) if x is not None]
        priced = sum(1 for x in items if x.price is not None)
        self.last_report = (
            f"{len(candidates)} lot(s) candidat(s), {len(items)} retenu(s), {priced} prix courant(s) exact(s)"
            + (" via navigateur" if used_browser else "")
        )
        return items
