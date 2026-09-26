from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import Watch
from app.sources.base import AuctionItem, SourceUnavailableError
from app.sources.interencheres_reference import ReferenceLot, extract_lots_reference
from app.sources.web_common import DEFAULT_BROWSER_UA, clean_text, labelled_price, parse_price, price_matches, stable_id

log = logging.getLogger(__name__)

LOT_ID_RE = re.compile(r"/lot-(\d+)\.html", re.I)
LOT_URL_RE = re.compile(r"/lot-\d+\.html(?:[?#].*)?$", re.I)
SALE_TYPE_RE = re.compile(r"\b(Live|Chrono|Catalogue)\b", re.I)
ESTIMATE_RE = re.compile(
    r"(?:Estimation|Estimé(?:e)?|Valeur)\s*:?\s*"
    r"(?P<low>\d[\d\s\u00a0.,]{0,14})\s*(?:€|EUR)"
    r"(?:\s*[-–à]\s*(?P<high>\d[\d\s\u00a0.,]{0,14})\s*(?:€|EUR))?",
    re.I,
)


@dataclass(slots=True)
class FetchResult:
    html: str
    url: str
    mode: str
    status: int | None


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> list[str]:
    return [t for t in _norm(value).split() if len(t) >= 2]


# These are category *hints*, not a fixed product catalogue.  The live category
# sitemap is also fetched and ranked.  Hints mainly bridge brand/model terms to
# Interencheres taxonomy words that are not literally present in the query.
QUERY_HINTS: tuple[tuple[set[str], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        {"macbook", "macbookpro", "macbookair", "imac", "macmini", "laptop", "notebook", "ordinateur", "pc"},
        ("ordinateur", "portable", "informatique"),
        (
            "/biens-equipement/ordinateurs-portables-et-fixes/",
            "/biens-equipement/informatique-et-telephonie/",
        ),
    ),
    (
        {"rtx", "geforce", "nvidia", "radeon", "gpu", "graphique", "ssd", "ram", "processeur", "cpu", "composant"},
        ("peripherique", "composant", "informatique", "ordinateur"),
        (
            "/biens-equipement/peripheriques-et-composants-informatiques/",
            "/biens-equipement/informatique-et-telephonie/",
            "/biens-equipement/ordinateurs-portables-et-fixes/",
        ),
    ),
    (
        {"iphone", "smartphone", "telephone", "galaxy", "pixel"},
        ("telephone", "mobile", "smartphone"),
        (
            "/biens-equipement/telephones-mobiles-et-smartphones/",
            "/biens-equipement/informatique-et-telephonie/",
        ),
    ),
    (
        {"ipad", "tablette", "tablet"},
        ("tablette", "informatique"),
        (
            "/biens-equipement/tablettes-et-accessoires/",
            "/biens-equipement/informatique-et-telephonie/",
        ),
    ),
    (
        {"ps5", "playstation", "xbox", "switch", "console", "nintendo"},
        ("console", "jeux", "multimedia"),
        (
            "/biens-equipement/consoles-de-jeux-et-accessoires/",
            "/biens-equipement/loisirs-et-multimedia/",
        ),
    ),
    (
        {"rolex", "omega", "cartier", "seiko", "montre", "watch"},
        ("montre", "horlogerie"),
        ("/art-decoration/montres/", "/art-decoration/horlogerie/"),
    ),
    (
        {"bague", "collier", "bracelet", "bijou", "bijoux", "diamant", "saphir", "rubis"},
        ("bijoux", "joaillerie"),
        ("/art-decoration/bijoux/", "/art-decoration/mode-et-bijoux/"),
    ),
    (
        {"vin", "champagne", "whisky", "cognac", "spiritueux"},
        ("vin", "spiritueux"),
        ("/art-decoration/vin-et-spiritueux/",),
    ),
    (
        {"voiture", "auto", "automobile", "bmw", "mercedes", "audi", "peugeot", "renault", "citroen", "porsche"},
        ("vehicule", "automobile"),
        ("/vehicules/vehicules/",),
    ),
)

# Static fallbacks discovered from Interencheres' public category sitemap.  The
# runtime still tries to read the sitemap so new categories can be ranked.
STATIC_CATEGORY_PATHS: tuple[str, ...] = (
    "/biens-equipement/informatique-et-telephonie/",
    "/biens-equipement/ordinateurs-portables-et-fixes/",
    "/biens-equipement/peripheriques-et-composants-informatiques/",
    "/biens-equipement/tablettes-et-accessoires/",
    "/biens-equipement/telephones-mobiles-et-smartphones/",
    "/biens-equipement/loisirs-et-multimedia/",
    "/biens-equipement/consoles-de-jeux-et-accessoires/",
    "/biens-equipement/appareils-photo-et-cameras/",
    "/biens-equipement/marchandises-neuves-et-stocks/",
    "/biens-equipement/materiels-professionnels/",
    "/art-decoration/montres/",
    "/art-decoration/horlogerie/",
    "/art-decoration/bijoux/",
    "/art-decoration/mode-et-bijoux/",
    "/art-decoration/vin-et-spiritueux/",
    "/art-decoration/jouets-et-modelisme/",
    "/art-decoration/bd-manga-et-comics/",
    "/art-decoration/instruments-de-musique/",
    "/vehicules/vehicules/",
)


class InterencheresSource:
    """Interencheres connector that avoids the currently blocked search route.

    V7 proved that the public `sharifulnrv/interencheres-scraper` strategy now
    receives HTTP 403 before parsing on some connections.  V8 therefore does
    *not* call `/recherche/lots` at all.

    Strategy:
      1. Resolve relevant public category pages from Interencheres' category
         sitemap + a few brand/product taxonomy hints.
      2. Read those category pages and filter cards locally by the watch query.
      3. If direct HTTP is refused, optionally attach to a real local Chromium
         session over CDP.  Any human verification remains manual; this code
         does not solve or bypass CAPTCHAs.
    """

    name = "interencheres"
    base_url = "https://www.interencheres.com"
    categories_sitemap_url = base_url + "/sitemap.categories.html"

    def __init__(self) -> None:
        self.last_report = ""
        self._category_cache: list[str] | None = None
        self._category_cache_at: datetime | None = None
        # V8.4: per-scan CDP state.  The real browser is never closed by the
        # bot; only the Playwright attachment and our temporary tab are.
        self._scan_force_cdp = False
        self._cdp_pw = None
        self._cdp_browser = None
        self._cdp_context = None
        self._cdp_page = None

    @property
    def status_label(self) -> str:
        return "interencheres (catégories publiques + navigateur local)"

    async def close(self) -> None:
        await self._close_cdp_session()

    @staticmethod
    def _headers(referer: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": DEFAULT_BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    async def _cdp_endpoint_alive(self) -> bool:
        cdp_url = (settings.interencheres_cdp_url or "").strip().rstrip("/")
        if not cdp_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=settings.interencheres_cdp_health_timeout_seconds) as client:
                response = await client.get(cdp_url + "/json/version")
            return response.status_code == 200
        except Exception:
            return False

    async def _ensure_cdp_session(self) -> None:
        if self._cdp_page is not None:
            try:
                if not self._cdp_page.is_closed():
                    return
            except Exception:
                pass

        await self._close_cdp_session()
        cdp_url = (settings.interencheres_cdp_url or "").strip()
        if not cdp_url:
            raise SourceUnavailableError(
                "INTERENCHERES_CDP_URL est vide. Lance tools/start_interencheres_browser.ps1."
            )
        try:
            from playwright.async_api import async_playwright
            self._cdp_pw = await async_playwright().start()
            self._cdp_browser = await self._cdp_pw.chromium.connect_over_cdp(
                cdp_url, timeout=settings.interencheres_browser_timeout_ms
            )
            if not self._cdp_browser.contexts:
                raise SourceUnavailableError(
                    "Navigateur CDP connecté mais aucun contexte Chrome/Edge n'est disponible."
                )
            self._cdp_context = self._cdp_browser.contexts[0]
            self._cdp_page = await self._cdp_context.new_page()
            self._cdp_page.set_default_timeout(settings.interencheres_browser_timeout_ms)
        except SourceUnavailableError:
            await self._close_cdp_session()
            raise
        except Exception as exc:
            await self._close_cdp_session()
            raise SourceUnavailableError(
                f"Impossible de joindre le navigateur local Interencheres sur {cdp_url}: "
                f"{type(exc).__name__}: {exc}. Lance tools/start_interencheres_browser.ps1 puis laisse la fenêtre ouverte."
            ) from exc

    async def _close_cdp_session(self) -> None:
        page, pw = self._cdp_page, self._cdp_pw
        self._cdp_page = None
        self._cdp_context = None
        self._cdp_browser = None
        self._cdp_pw = None
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass

    async def _http_fetch(self, url: str, referer: str | None = None) -> tuple[str | None, int | None]:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=settings.interencheres_timeout_seconds,
                headers=self._headers(referer),
            ) as client:
                response = await client.get(url)
            if response.status_code == 200:
                return response.text, 200
            return None, response.status_code
        except Exception as exc:
            log.debug("interencheres direct HTTP failed url=%s: %s", url, exc)
            return None, None

    async def _cdp_fetch(self, url: str) -> FetchResult:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        except Exception as exc:  # pragma: no cover
            raise SourceUnavailableError(f"Playwright indisponible: {exc}") from exc

        attempts = max(1, settings.interencheres_browser_page_retries + 1)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                await self._ensure_cdp_session()
                page = self._cdp_page
                if page is None:
                    raise RuntimeError("page CDP absente après connexion")

                response = None
                navigation_timed_out = False
                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=settings.interencheres_browser_timeout_ms,
                    )
                except PlaywrightTimeoutError as exc:
                    navigation_timed_out = True
                    last_exc = exc
                    log.warning(
                        "interencheres: navigation lente page=%s tentative=%s/%s; lecture du HTML déjà chargé",
                        url, attempt, attempts,
                    )

                settle_ms = (
                    settings.interencheres_cdp_direct_settle_ms
                    if self._scan_force_cdp
                    else settings.interencheres_browser_settle_ms
                )
                if settle_ms > 0:
                    await page.wait_for_timeout(settle_ms)
                html = await page.content()
                status = response.status if response else None
                visible = _norm(BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:12000])

                challenge_markers = (
                    "just a moment",
                    "verification que vous etes humain",
                    "verifiez que vous etes humain",
                    "captcha",
                    "access denied",
                )
                if status in {403, 429} or any(marker in visible for marker in challenge_markers):
                    raise SourceUnavailableError(
                        "Interencheres demande encore une vérification dans le navigateur local. "
                        "Ouvre la fenêtre Chrome/Edge dédiée, termine la vérification manuellement puis relance /scan."
                    )

                if navigation_timed_out and len(html) < 1500:
                    raise PlaywrightTimeoutError(
                        f"navigation timeout et HTML incomplet ({len(html)} octets)"
                    )

                return FetchResult(html=html, url=page.url, mode="cdp", status=status)

            except SourceUnavailableError:
                raise
            except Exception as exc:
                last_exc = exc
                # The CDP attachment or tab may have become stale. Reconnect
                # only on an actual page failure; normal pages reuse one tab.
                await self._close_cdp_session()
                if attempt < attempts:
                    log.warning(
                        "interencheres: erreur navigateur page=%s tentative=%s/%s: %s: %s; reconnexion CDP",
                        url, attempt, attempts, type(exc).__name__, exc,
                    )
                    await asyncio.sleep(max(0.0, settings.interencheres_browser_retry_delay_seconds))
                    continue
                raise SourceUnavailableError(
                    "Navigateur Interencheres joignable mais page impossible à charger après "
                    f"{attempts} tentative(s): {type(exc).__name__}: {exc}"
                ) from exc

        raise SourceUnavailableError(
            f"Interencheres: échec navigateur: {type(last_exc).__name__ if last_exc else 'erreur inconnue'}"
        )

    async def _fetch(self, url: str, referer: str | None = None) -> FetchResult:
        # V8.4: during a real scan, if the local browser is already available,
        # go straight through CDP.  The previous behaviour generated one known
        # 403 per page before doing the useful browser navigation.
        if self._scan_force_cdp:
            return await self._cdp_fetch(url)

        html, status = await self._http_fetch(url, referer)
        if html is not None:
            return FetchResult(html=html, url=url, mode="http", status=status)

        if status in {403, 429}:
            log.info("interencheres: HTTP %s sur %s, bascule navigateur local CDP", status, url)
        else:
            log.info("interencheres: HTTP direct indisponible sur %s, bascule navigateur local CDP", url)
        return await self._cdp_fetch(url)

    @staticmethod
    def _extract_category_paths(html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[str] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "interencheres.com/" not in href:
                continue
            parsed = urlparse(href)
            path = parsed.path
            if not path.endswith("/") or "/en-US/" in path or path.endswith("/ventes/"):
                continue
            if not (path.startswith("/art-decoration/") or path.startswith("/biens-equipement/") or path.startswith("/vehicules/")):
                continue
            if path.count("/") < 3:
                continue
            if path not in seen:
                seen.add(path)
                out.append(path)
        # Sitemap pages can occasionally be returned as a plain list rather
        # than semantic anchors; keep a URL regex fallback.
        for href in re.findall(r"https://www\.interencheres\.com/(?:art-decoration|biens-equipement|vehicules)/[^\s\"'<>]+/", html, re.I):
            path = urlparse(href).path
            if "/en-US/" not in path and "/ventes/" not in path and path not in seen:
                seen.add(path)
                out.append(path)
        return out

    async def _category_paths(self) -> list[str]:
        now = datetime.now(timezone.utc)
        if self._category_cache is not None and self._category_cache_at and now - self._category_cache_at < timedelta(hours=12):
            return self._category_cache

        if self._scan_force_cdp:
            # The sitemap HTTP route is also blocked on the user's connection.
            # The static taxonomy is enough for product/category routing and
            # avoids another guaranteed 403 at the beginning of every scan.
            html, status = None, None
            paths = list(STATIC_CATEGORY_PATHS)
        else:
            html, status = await self._http_fetch(self.categories_sitemap_url, self.base_url + "/")
            paths = self._extract_category_paths(html) if html else []
        if not paths:
            # Do not require the browser merely to resolve taxonomy.  Static
            # known-good paths are enough to continue.
            if status:
                log.info("interencheres category sitemap HTTP %s; using static taxonomy fallback", status)
            paths = list(STATIC_CATEGORY_PATHS)
        else:
            # Merge static paths in case the sitemap omits a category while it
            # is being regenerated.
            for path in STATIC_CATEGORY_PATHS:
                if path not in paths:
                    paths.append(path)

        self._category_cache = paths
        self._category_cache_at = now
        return paths

    @staticmethod
    def _expanded_terms(query: str) -> tuple[set[str], list[str]]:
        query_tokens = set(_tokens(query))
        expanded = set(query_tokens)
        direct_paths: list[str] = []
        for triggers, synonyms, paths in QUERY_HINTS:
            if query_tokens.intersection({_norm(x) for x in triggers}):
                expanded.update(_norm(x) for x in synonyms)
                direct_paths.extend(paths)
        return expanded, direct_paths

    async def _resolve_categories(self, query: str) -> list[str]:
        paths = await self._category_paths()
        terms, direct_paths = self._expanded_terms(query)
        scores: dict[str, int] = {}

        for path in paths:
            slug = _norm(path.strip("/").split("/")[-1])
            words = set(slug.split())
            score = 0
            for term in terms:
                if term in words:
                    score += 7
                elif term and term in slug:
                    score += 4
                elif any(term in word or word in term for word in words if len(word) >= 4 and len(term) >= 4):
                    score += 2
            scores[path] = score

        # Product/brand aliases should dominate pure lexical ranking.
        for rank, path in enumerate(direct_paths):
            scores[path] = scores.get(path, 0) + 100 - rank

        ranked = [path for path, score in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])) if score > 0]
        if not ranked:
            # Generic fallback: these broad pages cover most ordinary consumer
            # goods without hitting the protected search endpoint.
            ranked = [
                "/biens-equipement/marchandises-neuves-et-stocks/",
                "/biens-equipement/materiels-professionnels/",
                "/art-decoration/collections/",
            ]

        top_k = max(1, settings.interencheres_category_top_k)
        selected: list[str] = []
        for path in ranked:
            if path not in selected:
                selected.append(path)
            if len(selected) >= top_k:
                break
        return [urljoin(self.base_url + "/", path.lstrip("/")) for path in selected]

    @staticmethod
    def _query_matches(text: str, query: str) -> bool:
        haystack = _norm(text)
        needle = _norm(query)
        if not needle:
            return True
        if needle in haystack:
            return True
        tokens = [t for t in needle.split() if len(t) >= 2]
        return bool(tokens) and all(t in haystack for t in tokens)

    @staticmethod
    def _extract_estimate(raw: str) -> str | None:
        m = ESTIMATE_RE.search(raw or "")
        if not m:
            return None
        low = clean_text(m.group("low") or "")
        high = clean_text(m.group("high") or "")
        return f"{low} € - {high} €" if high else f"{low} €"

    @staticmethod
    def _clean_anchor_title(raw: str, sale_type: str | None = None) -> str:
        title = clean_text(raw)
        # Anchor fallbacks sometimes contain the lot number + UI metadata
        # before the actual title, e.g.
        # "117 Estimation : 270 € Déjà vu APPLE MACBOOK ...".
        title = re.sub(
            r"^\s*\d+\s+(?=(?:Estimation|Estimé(?:e)?|Valeur|Déjà\s+vu)\b)",
            "", title, flags=re.I,
        )
        title = re.sub(r"^\d+\s*/\s*\d+\s*", "", title)
        title = re.sub(
            r"^(?:Estimation|Estimé(?:e)?|Valeur)\s*:?\s*"
            r"\d[\d\s\u00a0.,]*\s*(?:€|EUR)"
            r"(?:\s*[-–à]\s*\d[\d\s\u00a0.,]*\s*(?:€|EUR))?\s*",
            "", title, flags=re.I,
        )
        title = re.sub(r"^(?:Lot\s*(?:n[°o]\s*)?\d+\s*)?Déjà\s+vu\s*", "", title, flags=re.I)
        if sale_type:
            m = re.search(rf"\b{re.escape(sale_type)}\b", title, re.I)
            if m and m.start() > 0:
                title = title[:m.start()]
        return clean_text(title).strip(" -–:")

    @staticmethod
    def _generic_anchor_lots(html: str) -> tuple[list[ReferenceLot], int]:
        soup = BeautifulSoup(html, "html.parser")
        lots: list[ReferenceLot] = []
        seen: set[str] = set()
        anchors = []
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if LOT_URL_RE.search(href):
                anchors.append(a)

        for a in anchors:
            href = str(a.get("href") or "")
            url = urljoin("https://www.interencheres.com/", href)
            if url in seen:
                continue
            seen.add(url)
            raw = clean_text(a.get_text(" ", strip=True))
            if not raw:
                continue

            sale_m = SALE_TYPE_RE.search(raw)
            sale_type = sale_m.group(1).title() if sale_m else None

            title = InterencheresSource._clean_anchor_title(raw, sale_type)

            seller = None
            seller_m = re.search(r"Proposé\s+par\s+(.+)$", raw, re.I)
            if seller_m:
                seller = clean_text(seller_m.group(1))

            lots.append(
                ReferenceLot(
                    title=title or raw[:500],
                    price_text=None,
                    sale_type=sale_type,
                    status="Auction completed" if re.search(r"\b(?:Adjugé|Vendu|Terminée?)\b", raw, re.I) else "Auction continue",
                    image_url=None,
                    date_text=None,
                    seller=seller,
                    lot_url=url,
                    raw_text=raw,
                )
            )
        return lots, len(anchors)

    @classmethod
    def _parse_category_lots(cls, html: str) -> tuple[list[ReferenceLot], int, str]:
        lots, count = extract_lots_reference(html, cls.base_url + "/")
        if lots:
            return lots, count, "cards"
        lots, count = cls._generic_anchor_lots(html)
        return lots, count, "anchors"

    @staticmethod
    def _external_id(lot: ReferenceLot) -> str:
        url = lot.lot_url or ""
        m = LOT_ID_RE.search(url)
        if m:
            return m.group(1)
        return stable_id("interencheres", url, lot.title)

    @staticmethod
    def _is_completed(lot: ReferenceLot) -> bool:
        if lot.status == "Auction completed":
            return True
        text = _norm(f"{lot.raw_text} {lot.price_text or ''}")
        return any(marker in text for marker in ("adjuge", "vendu", "vente terminee"))

    @staticmethod
    def _timing_text(lot: ReferenceLot) -> str | None:
        if lot.date_text:
            return clean_text(lot.date_text)
        text = clean_text(lot.raw_text)
        patterns = [
            r"(?:Fin|Clôture)\s+dans\s+\d+\s*j(?:ours?)?(?:\s+\d+\s*h(?:\s*\d+\s*m)?)?",
            r"(?:Fin|Clôture)\s+dans\s+\d+\s*h(?:\s*\d+\s*m)?",
            r"Clôture\s+le\s+\d{1,2}\s+[A-Za-zÀ-ÿ-]+\s+\d{4}\s+à\s+partir\s+de\s+\d{1,2}h\d{2}",
            r"Aujourd['’]hui\s+à\s+\d{1,2}h\d{2}",
            r"Demain\s+à\s+\d{1,2}h\d{2}",
            r"(?:Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)\s+\d{1,2}\s+[A-Za-zÀ-ÿ-]+(?:\s+\d{4})?\s+à\s+\d{1,2}h\d{2}",
            r"\d{1,2}/\d{1,2}/\d{4}\s*(?:à|:)\s*\d{1,2}h?\d{0,2}",
            r"\d{1,2}/\d{1,2}/\d{4}",
            r"\bEn cours\b",
            r"\bVa débuter\b",
            r"\bÀ\s+\d{1,2}h\d{2}\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.I)
            if m:
                return clean_text(m.group(0))
        return None

    @staticmethod
    def _extract_price(lot: ReferenceLot) -> tuple[float | None, str | None, str | None]:
        price, currency, label = labelled_price(
            lot.raw_text,
            (
                "Enchère actuelle",
                "Enchère en cours",
                "Offre actuelle",
                "Prix actuel",
                "Mise à prix",
                "Prix de départ",
            ),
        )
        if price is not None:
            if label in {"Offre actuelle", "Enchère en cours"}:
                label = "Enchère actuelle"
            return price, currency, label

        amount = clean_text(lot.price_text or "")
        folded = _norm(amount)
        if amount and not any(x in folded for x in ("estimation", "adjuge", "vendu")):
            price, currency = parse_price(amount)
            if price is not None:
                return price, currency, "Enchère actuelle"
        return None, None, None

    def _convert(self, lot: ReferenceLot, watch: Watch) -> AuctionItem | None:
        if not lot.lot_url or self._is_completed(lot):
            return None
        searchable = f"{lot.title} {lot.raw_text}"
        if not self._query_matches(searchable, watch.query):
            return None

        title = clean_text(lot.title)
        if not title or title == "N/A":
            title = clean_text(lot.raw_text)[:500] or "Lot Interencheres"

        price, currency, price_label = self._extract_price(lot)
        if not price_matches(watch, price):
            return None

        return AuctionItem(
            source=self.name,
            external_id=self._external_id(lot),
            title=title[:500],
            url=lot.lot_url,
            price=price,
            currency=currency or "EUR",
            image_url=lot.image_url,
            seller=clean_text(lot.seller or "") or None,
            auction_type=lot.sale_type,
            timing_text=self._timing_text(lot),
            price_label=price_label,
            estimate_text=self._extract_estimate(lot.raw_text),
        )

    async def search(self, watch: Watch) -> list[AuctionItem]:
        # Prefer the already-open real browser.  This is the path that the
        # standalone probe proved works on the user's machine.
        self._scan_force_cdp = bool(
            settings.interencheres_prefer_cdp and await self._cdp_endpoint_alive()
        )
        if self._scan_force_cdp:
            log.info(
                "interencheres: navigateur CDP détecté; mode direct activé (aucun essai HTTP sur les pages Interencheres)"
            )
            await self._ensure_cdp_session()

        try:
            categories = await self._resolve_categories(watch.query)
            max_pages = max(1, settings.interencheres_max_pages)
            out: list[AuctionItem] = []
            seen: set[str] = set()
            reports: list[str] = []
            used_cdp = self._scan_force_cdp
            any_page_ok = False

            for category_url in categories:
                category_name = category_url.rstrip("/").split("/")[-1]
                previous_ids: set[str] | None = None
                category_pages = 0
                category_cards = 0
                category_matches = 0
                parse_modes: set[str] = set()
                stop_reason = f"limite {max_pages} pages"

                for page_no in range(1, max_pages + 1):
                    sep = "&" if "?" in category_url else "?"
                    page_url = category_url if page_no == 1 else f"{category_url}{sep}page={page_no}"
                    try:
                        fetched = await self._fetch(page_url, self.base_url + "/")
                    except SourceUnavailableError as exc:
                        if not any_page_ok:
                            raise
                        stop_reason = f"source devenue indisponible: {exc}"
                        break

                    any_page_ok = True
                    used_cdp = used_cdp or fetched.mode == "cdp"
                    lots, card_count, parse_mode = self._parse_category_lots(fetched.html)
                    parse_modes.add(parse_mode)
                    category_pages += 1
                    category_cards += card_count

                    page_ids = {self._external_id(lot) for lot in lots if lot.lot_url}
                    if not lots:
                        stop_reason = f"page {page_no} sans lot"
                        break
                    if previous_ids is not None and page_ids and page_ids == previous_ids:
                        stop_reason = f"pagination HTML répétée à la page {page_no}"
                        break
                    previous_ids = page_ids

                    for lot in lots:
                        item = self._convert(lot, watch)
                        if item is None or item.external_id in seen:
                            continue
                        seen.add(item.external_id)
                        out.append(item)
                        category_matches += 1

                    every = max(0, settings.interencheres_progress_every_pages)
                    if every and page_no % every == 0:
                        log.info(
                            "interencheres: progression catégorie=%s page=%s/%s lots=%s matches=%s mode=%s",
                            category_name, page_no, max_pages, category_cards, category_matches, fetched.mode,
                        )

                    delay = (
                        settings.interencheres_cdp_direct_page_delay_seconds
                        if self._scan_force_cdp
                        else settings.interencheres_category_page_delay_seconds
                    )
                    await asyncio.sleep(max(0.0, delay))

                reports.append(
                    f"{category_name}: pages={category_pages}/{max_pages}, lots={category_cards}, "
                    f"matches={category_matches}, parse={'+'.join(sorted(parse_modes)) or 'n/a'}, arrêt={stop_reason}"
                )

            mode = "CDP direct (connexion réutilisée)" if self._scan_force_cdp else (
                "CDP navigateur local" if used_cdp else "HTTP catégories publiques"
            )
            self.last_report = (
                f"mode={mode}; recherche protégée /recherche/lots non utilisée; "
                f"catégories={len(categories)} [{', '.join(u.rstrip('/').split('/')[-1] for u in categories)}]; "
                f"retenues={len(out)}; " + " | ".join(reports)
            )
            log.info("interencheres: %s", self.last_report)
            return out
        finally:
            # Keep the user's Chrome/Edge window open, but detach Playwright and
            # close only the temporary tab created for this scan.
            await self._close_cdp_session()
            self._scan_force_cdp = False

