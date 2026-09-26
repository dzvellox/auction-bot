from __future__ import annotations

import hashlib
import json
import logging
import re
from html import unescape
from urllib.parse import urljoin

import httpx

from app.config import settings
from app.models import Watch
from app.sources.base import AuctionItem, SourceUnavailableError

log = logging.getLogger(__name__)

# Support both "100 €" and "€ 100". Catawiki currently renders current bids
# using the second form, while most French auction sites use the first one.
PRICE_SUFFIX_RE = re.compile(
    r"(?P<price>\d[\d\s\u00a0.,]{0,16})\s*(?P<currency>€|EUR|GBP|£|USD|\$)",
    re.I,
)
PRICE_PREFIX_RE = re.compile(
    r"(?P<currency>€|EUR|GBP|£|USD|\$)\s*(?P<price>\d[\d\s\u00a0.,]{0,16})",
    re.I,
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
ANCHOR_RE = re.compile(r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<body>.*?)</a>', re.I | re.S)

DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)


def clean_text(value: str) -> str:
    value = unescape(TAG_RE.sub(" ", value or ""))
    return SPACE_RE.sub(" ", value).strip()


def _normalize_numeric_price(raw: str) -> float | None:
    raw = raw.replace("\u00a0", " ").replace(" ", "").strip()
    if not raw:
        return None

    # French decimal comma. Thousands separators can be dots or commas on some
    # international pages, so keep only the final separator when plausible.
    if raw.count(",") == 1 and raw.count(".") == 0:
        raw = raw.replace(",", ".")
    elif raw.count(".") == 1 and raw.count(",") == 1:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif raw.count(",") > 1:
        raw = raw.replace(",", "")

    try:
        return float(raw)
    except ValueError:
        return None


def parse_price(text: str) -> tuple[float | None, str | None]:
    value = text or ""
    matches: list[tuple[int, re.Match[str]]] = []
    for regex in (PRICE_SUFFIX_RE, PRICE_PREFIX_RE):
        m = regex.search(value)
        if m:
            matches.append((m.start(), m))
    if not matches:
        return None, None

    _, m = min(matches, key=lambda x: x[0])
    price = _normalize_numeric_price(m.group("price"))
    if price is None:
        return None, None

    cur = m.group("currency").upper()
    currency = {
        "€": "EUR",
        "EUR": "EUR",
        "£": "GBP",
        "GBP": "GBP",
        "$": "USD",
        "USD": "USD",
    }.get(cur, cur)
    return price, currency


def labelled_price(text: str, labels: tuple[str, ...], window: int = 220) -> tuple[float | None, str | None, str | None]:
    """Return a price belonging to a known semantic label.

    The slice is stopped before another price label or an estimate/value block.
    Without that guard, text such as ``Offre actuelle — aucune offre —
    Estimation € 500`` could incorrectly report 500 € as the current bid.
    """

    value = text or ""
    folded = value.casefold()
    blockers = (
        "estimation",
        "estimate",
        "expert estimate",
        "expert's estimate",
        "valeur indicative",
        "valeur estimée",
        "valeur estimee",
        "retail price",
        "prix neuf",
    )
    for label in labels:
        label_folded = label.casefold()
        idx = folded.find(label_folded)
        if idx < 0:
            continue
        start = idx + len(label)
        end = min(len(value), start + window)

        # Do not let a missing current bid consume the following start price,
        # estimate, or another semantic price field.
        for other in (*labels, *blockers):
            other_folded = other.casefold()
            search_from = start
            next_idx = folded.find(other_folded, search_from, end)
            if next_idx >= 0:
                # Ignore the label occurrence we are currently processing.
                if other_folded == label_folded and next_idx == idx:
                    continue
                end = min(end, next_idx)

        price, currency = parse_price(value[start:end])
        if price is not None:
            return price, currency, label
    return None, None, None


def price_matches(watch: Watch, price: float | None) -> bool:
    # Unknown prices are not discarded: many future live sales do not expose a
    # current bid yet. Telegram will explicitly say the price is unavailable.
    if price is None:
        return True
    if watch.min_price is not None and price < watch.min_price:
        return False
    if watch.max_price is not None and price > watch.max_price:
        return False
    return True


def stable_id(source: str, url: str, title: str) -> str:
    return hashlib.sha256(f"{source}|{url}|{title}".encode()).hexdigest()[:32]


def query_tokens(query: str) -> list[str]:
    return [t.casefold() for t in re.findall(r"[\w-]+", query, re.UNICODE) if len(t) >= 2]


def text_matches_query(text: str, query: str) -> bool:
    folded = (text or "").casefold()
    tokens = query_tokens(query)
    return not tokens or all(tok in folded for tok in tokens)


def extract_jsonld_items(html: str, source: str, base_url: str, watch: Watch) -> list[AuctionItem]:
    out: list[AuctionItem] = []
    scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    for raw in scripts:
        try:
            data = json.loads(unescape(raw).strip())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for obj in stack:
            if not isinstance(obj, dict):
                continue
            candidates = obj.get("itemListElement") or [] if obj.get("@type") == "ItemList" else [obj]
            for cand in candidates:
                if isinstance(cand, dict) and isinstance(cand.get("item"), dict):
                    cand = cand["item"]
                if not isinstance(cand, dict):
                    continue
                title = clean_text(str(cand.get("name") or cand.get("headline") or ""))
                url = cand.get("url") or cand.get("@id")
                if not title or not url or not text_matches_query(title, watch.query):
                    continue
                offers = cand.get("offers") if isinstance(cand.get("offers"), dict) else {}
                price = None
                currency = None
                try:
                    if offers.get("price") is not None:
                        price = float(str(offers.get("price")).replace(",", "."))
                        currency = offers.get("priceCurrency")
                except ValueError:
                    pass
                if not price_matches(watch, price):
                    continue
                abs_url = urljoin(base_url, str(url))
                out.append(
                    AuctionItem(
                        source,
                        stable_id(source, abs_url, title),
                        title,
                        abs_url,
                        price,
                        currency,
                        price_label="Prix",
                    )
                )
    return out


class PublicWebSource:
    """Shared HTTP + Playwright helper for public auction pages.

    Browser fallback is a normal page load only. It does not log in or solve
    human-verification challenges.
    """

    name = "web"
    base_url = ""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0),
            headers={
                "User-Agent": DEFAULT_BROWSER_UA,
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Cache-Control": "no-cache",
            },
        )
        self._pw = None
        self._browser = None
        self._browser_context = None
        self._browser_warmed = False
        self.last_report = ""

    async def close(self) -> None:
        await self.client.aclose()
        if self._browser_context:
            await self._browser_context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    def search_urls(self, query: str) -> list[str]:
        raise NotImplementedError

    def is_result_url(self, href: str) -> bool:
        return True

    def parse_html(self, html: str, final_url: str, watch: Watch) -> list[AuctionItem]:
        items = extract_jsonld_items(html, self.name, final_url, watch)
        seen = {x.url for x in items}
        for m in ANCHOR_RE.finditer(html):
            href = unescape(m.group("href"))
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            abs_url = urljoin(final_url, href)
            if abs_url in seen or not self.is_result_url(abs_url):
                continue
            text = clean_text(m.group("body"))
            if len(text) < 4 or not text_matches_query(text, watch.query):
                continue
            price, currency = parse_price(text)
            if not price_matches(watch, price):
                continue
            items.append(
                AuctionItem(
                    self.name,
                    stable_id(self.name, abs_url, text),
                    text[:500],
                    abs_url,
                    price,
                    currency,
                    price_label="Prix",
                )
            )
            seen.add(abs_url)
        return items

    async def _ensure_browser(self) -> None:
        if self._browser_context:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise SourceUnavailableError(
                f"{self.name}: page dynamique/protégée et Playwright n'est pas installé. "
                "Lance `pip install -r requirements.txt` puis `python -m playwright install chromium`."
            ) from exc

        self._pw = await async_playwright().start()
        attempts: list[str | None] = []
        if settings.browser_channel:
            attempts.append(settings.browser_channel)
        for channel in ("msedge", "chrome", None):
            if channel not in attempts:
                attempts.append(channel)

        launch_errors: list[str] = []
        for channel in attempts:
            try:
                kwargs = {"headless": settings.browser_headless}
                if channel:
                    kwargs["channel"] = channel
                self._browser = await self._pw.chromium.launch(**kwargs)
                break
            except Exception as exc:
                launch_errors.append(f"{channel or 'chromium'}={type(exc).__name__}")
        if not self._browser:
            await self._pw.stop()
            self._pw = None
            raise SourceUnavailableError(
                f"{self.name}: aucun navigateur Playwright disponible ({', '.join(launch_errors)}). "
                "Lance `python -m playwright install chromium`."
            )
        self._browser_context = await self._browser.new_context(
            user_agent=DEFAULT_BROWSER_UA,
            locale="fr-FR",
            viewport={"width": 1440, "height": 1100},
        )

    async def _browser_fetch(self, url: str, wait_ms: int = 1200) -> tuple[str, str]:
        await self._ensure_browser()
        page = await self._browser_context.new_page()
        try:
            if not self._browser_warmed and self.base_url:
                try:
                    await page.goto(self.base_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
                    self._browser_warmed = True
                except Exception:
                    pass
            response = await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(settings.browser_timeout_ms, 8000))
            except Exception:
                pass
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)
            html = await page.content()
            title = (await page.title()).casefold()
            body = (await page.locator("body").inner_text(timeout=3000)).casefold()
            status = response.status if response else 0
            blocked_markers = (
                "captcha",
                "access denied",
                "just a moment",
                "vérifions que vous êtes humain",
                "verify you are human",
            )
            if status in (401, 403, 429) or any(m in title or m in body[:5000] for m in blocked_markers):
                raise SourceUnavailableError(
                    f"{self.name}: le site refuse aussi le navigateur automatique "
                    f"(HTTP {status or 'inconnu'} / protection anti-bot)."
                )
            return html, page.url
        finally:
            await page.close()

    async def search(self, watch: Watch) -> list[AuctionItem]:
        errors: list[str] = []
        browser_needed = False

        for url in self.search_urls(watch.query):
            try:
                response = await self.client.get(url)
                if response.status_code in (401, 403, 429):
                    errors.append(f"{response.status_code} {response.url}")
                    browser_needed = True
                    continue
                response.raise_for_status()
                items = self.parse_html(response.text, str(response.url), watch)
                if items:
                    self.last_report = f"HTTP direct: {len(items)} résultat(s)"
                    return items
                # A 200 response can merely be an SPA shell ('Chargement...').
                body = clean_text(response.text).casefold()
                if len(body) < 500 or "chargement" in body[:500]:
                    browser_needed = True
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        if settings.enable_browser_fallback and browser_needed:
            browser_errors: list[str] = []
            log.info("%s: page vide/dynamique ou HTTP bloqué, tentative via navigateur", self.name)
            for browser_url in self.search_urls(watch.query):
                try:
                    html, final_url = await self._browser_fetch(browser_url)
                    items = self.parse_html(html, final_url, watch)
                    if items:
                        self.last_report = f"navigateur: {len(items)} résultat(s)"
                        return items
                except SourceUnavailableError:
                    raise
                except Exception as exc:
                    browser_errors.append(f"{type(exc).__name__}: {exc}")
            if browser_errors:
                errors.extend(f"browser={e}" for e in browser_errors[:2])
            else:
                self.last_report = "0 résultat après rendu navigateur"
                return []

        if errors and not browser_needed:
            raise SourceUnavailableError(f"{self.name}: aucune page de recherche exploitable ({'; '.join(errors[:3])})")
        self.last_report = "0 résultat"
        return []
