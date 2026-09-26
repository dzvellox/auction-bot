from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote_plus, unquote, urljoin

from bs4 import BeautifulSoup, Tag

from app.config import settings
from app.models import Watch
from app.sources.base import AuctionItem, SourceUnavailableError
from app.sources.web_common import PublicWebSource, clean_text, labelled_price, price_matches, stable_id, text_matches_query

log = logging.getLogger(__name__)
CURRENT_URL_RE = re.compile(r"https?://(?:www\.)?agorastore\.fr/fr/materiel-occasion/[^\s?#]+/agora-(\d+)", re.I)
LEGACY_URL_RE = re.compile(r"https?://(?:www\.)?agorastore\.fr/vente-occasion/.+?-(\d+)\.aspx", re.I)
REL_CURRENT_RE = re.compile(r"/fr/materiel-occasion/[^\s?#]+/agora-(\d+)", re.I)
REL_LEGACY_RE = re.compile(r"/vente-occasion/.+?-(\d+)\.aspx", re.I)


class AgorastoreSource(PublicWebSource):
    name = "agorastore"
    base_url = "https://www.agorastore.fr"

    @property
    def status_label(self) -> str:
        return "agorastore (rendu navigateur SPA)"

    def search_urls(self, query: str) -> list[str]:
        q = quote_plus(query)
        # Agorastore migrated its frontend in 2026. Keep several public route
        # variants; if they only return the SPA shell, V6 searches via the real
        # search input in Playwright instead of declaring 0 result immediately.
        return [
            f"{self.base_url}/fr/recherche?search={q}",
            f"{self.base_url}/fr/recherche?q={q}",
            f"{self.base_url}/fr/ventes-occasions?search={q}",
            f"{self.base_url}/ventes-occasions?search={q}",
            f"{self.base_url}/search?type=auction&search={q}",
        ]

    def is_result_url(self, href: str) -> bool:
        return bool(CURRENT_URL_RE.search(href) or LEGACY_URL_RE.search(href))

    @staticmethod
    def _extract_id(url: str) -> str:
        for regex in (CURRENT_URL_RE, LEGACY_URL_RE):
            m = regex.search(url)
            if m:
                return m.group(1)
        return stable_id("agorastore", url, "")

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
        slug = abs_url.rstrip("/").split("/")[-2] if "/agora-" in abs_url else abs_url.rsplit("/", 1)[-1]
        slug = re.sub(r"-\d+\.aspx$", "", slug, flags=re.I)
        return clean_text(unquote(slug).replace("-", " ")) or "Lot Agorastore"

    def _extract_candidates(self, html: str, final_url: str, watch: Watch) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        anchors = list(soup.find_all("a", href=REL_CURRENT_RE)) + list(soup.find_all("a", href=REL_LEGACY_RE))
        for anchor in anchors:
            if not isinstance(anchor, Tag):
                continue
            href = str(anchor.get("href") or "").strip()
            abs_url = urljoin(final_url, href).split("#", 1)[0]
            if abs_url in seen or not self.is_result_url(abs_url):
                continue
            title = self._title_from_anchor(anchor, abs_url)
            context = title
            parent = anchor.parent
            for _ in range(4):
                if not isinstance(parent, Tag):
                    break
                text = clean_text(parent.get_text(" ", strip=True))
                if 0 < len(text) < 1800:
                    context = f"{context} {text}"
                parent = parent.parent
            if not text_matches_query(context, watch.query):
                continue
            seen.add(abs_url)
            out.append((abs_url, title[:500]))
        return out

    async def _search_via_ui(self, query: str, watch: Watch) -> tuple[list[tuple[str, str]], str]:
        await self._ensure_browser()
        page = await self._browser_context.new_page()
        try:
            await page.goto(self.base_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(settings.browser_timeout_ms, 8000))
            except Exception:
                pass
            await page.wait_for_timeout(1200)

            selectors = [
                'input[type="search"]',
                'input[placeholder*="Recher" i]',
                'input[aria-label*="Recher" i]',
                'input[name*="search" i]',
                'input[id*="search" i]',
            ]
            used_selector = None
            for selector in selectors:
                locator = page.locator(selector)
                try:
                    if await locator.count() > 0 and await locator.first.is_visible():
                        used_selector = selector
                        await locator.first.fill(query)
                        await locator.first.press("Enter")
                        break
                except Exception:
                    continue

            if used_selector is None:
                return [], "champ de recherche introuvable dans l'interface"

            try:
                await page.wait_for_load_state("networkidle", timeout=min(settings.browser_timeout_ms, 10000))
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            html = await page.content()
            return self._extract_candidates(html, page.url, watch), f"recherche UI ({used_selector})"
        finally:
            await page.close()

    @staticmethod
    def _detail_from_text(text: str, url: str, fallback_title: str, watch: Watch) -> AuctionItem | None:
        page_text = clean_text(text)
        # Title is normally the first H1 when caller passes rendered HTML; the
        # fallback remains the card title if markup changed.
        soup = BeautifulSoup(text, "html.parser")
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True)) if isinstance(h1, Tag) else fallback_title
        if not title:
            title = fallback_title
        if not text_matches_query(f"{title} {page_text[:5000]}", watch.query):
            return None

        price, currency, label = labelled_price(
            page_text,
            ("Enchère actuelle", "Prix actuel", "Prix de départ"),
            window=260,
        )
        if not price_matches(watch, price):
            return None

        timing = None
        patterns = [
            r"Fin de vente\s*:?\s*(\d{1,2}/\d{1,2}/\d{4}\s*(?:À partir de|à|A partir de)?\s*\d{1,2}:\d{2})",
            r"Date de fin de vente\s*(?:Le)?\s*(\d{1,2}/\d{1,2}/\d{4}\s+à\s+\d{1,2}:\d{2})",
            r"La vente se termine dans\s*:?\s*([0-9A-Za-zÀ-ÿ :]+?)(?=\s+(?:Enchère actuelle|Prix|€|$))",
        ]
        for pattern in patterns:
            m = re.search(pattern, page_text, re.I)
            if m:
                timing = clean_text(m.group(1))[:120]
                break

        condition = None
        m = re.search(r"Etat général\s+(.{1,120}?)(?=\s+(?:Lieu de visite|IMPORTANT|Description|Modalités|$))", page_text, re.I)
        if m:
            condition = clean_text(m.group(1))[:120]

        seller = None
        m = re.search(r"\bVendeur\s+(.{1,120}?)(?=\s+(?:Questions|Une question|$))", page_text, re.I)
        if m:
            seller = clean_text(m.group(1))[:120]

        return AuctionItem(
            source="agorastore",
            external_id=AgorastoreSource._extract_id(url),
            title=title[:500],
            url=url,
            price=price,
            currency=currency or "EUR",
            auction_type="Chrono",
            timing_text=timing,
            condition=condition,
            seller=seller,
            price_label=label,
        )

    async def _detail_item(self, url: str, title: str, watch: Watch) -> AuctionItem | None:
        # Agorastore's current public HTML is often only "Chargement...". Render
        # details in browser first; fall back to HTTP only if it already contains data.
        if settings.enable_browser_fallback:
            try:
                html, final_url = await self._browser_fetch(url, wait_ms=900)
                item = self._detail_from_text(html, final_url, title, watch)
                if item is not None:
                    return item
            except SourceUnavailableError:
                raise
            except Exception as exc:
                log.debug("agorastore detail browser failed %s: %s", url, exc)

        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                return self._detail_from_text(response.text, str(response.url), title, watch)
        except Exception as exc:
            log.debug("agorastore detail HTTP failed %s: %s", url, exc)

        return AuctionItem(
            source=self.name,
            external_id=self._extract_id(url),
            title=title,
            url=url,
            price=None,
            currency="EUR",
            auction_type="Chrono",
        ) if price_matches(watch, None) else None

    async def search(self, watch: Watch) -> list[AuctionItem]:
        candidates: list[tuple[str, str]] = []
        method = ""
        errors: list[str] = []

        # First try public route variants cheaply. This catches future server-side
        # rendering without paying the browser cost.
        for url in self.search_urls(watch.query):
            try:
                response = await self.client.get(url)
                if response.status_code in (401, 403, 429):
                    errors.append(f"HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                candidates = self._extract_candidates(response.text, str(response.url), watch)
                if candidates:
                    method = "HTTP"
                    break
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        # The 2026 Agorastore frontend is a SPA. A 200 with no products is not
        # proof of zero results, so use the visible search bar in a real browser.
        if not candidates and settings.enable_browser_fallback:
            try:
                candidates, method = await self._search_via_ui(watch.query, watch)
            except SourceUnavailableError:
                raise
            except Exception as exc:
                errors.append(f"UI {type(exc).__name__}: {exc}")

        # Last browser fallback: open route variants directly in case the search
        # input's frontend behavior changes but query URLs still work.
        if not candidates and settings.enable_browser_fallback:
            for url in self.search_urls(watch.query):
                try:
                    html, final_url = await self._browser_fetch(url)
                    candidates = self._extract_candidates(html, final_url, watch)
                    if candidates:
                        method = "URL navigateur"
                        break
                except SourceUnavailableError:
                    raise
                except Exception as exc:
                    errors.append(f"browser {type(exc).__name__}: {exc}")

        if not candidates:
            self.last_report = "0 annonce trouvée après HTTP + recherche UI navigateur"
            if errors:
                log.info("agorastore: %s", "; ".join(errors[:3]))
            return []

        candidates = candidates[: max(1, settings.agorastore_max_results)]
        sem = asyncio.Semaphore(max(1, settings.agorastore_detail_concurrency))

        async def enrich(pair: tuple[str, str]) -> AuctionItem | None:
            async with sem:
                return await self._detail_item(pair[0], pair[1], watch)

        items = [x for x in await asyncio.gather(*(enrich(p) for p in candidates)) if x is not None]
        priced = sum(1 for x in items if x.price is not None)
        self.last_report = (
            f"{len(candidates)} annonce(s) candidate(s), {len(items)} retenue(s), "
            f"{priced} prix exact(s), méthode={method or 'inconnue'}"
        )
        return items
