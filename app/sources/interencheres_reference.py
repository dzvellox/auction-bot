"""Local adapter based on sharifulnrv/interencheres-scraper.

Reference project:
https://github.com/sharifulnrv/interencheres-scraper

The reference repository is MIT-licensed according to its README.  This module
keeps its important scraping assumptions deliberately close to the reference:
- cloudscraper Firefox/Windows session
- /recherche/lots?search=<query>&page=<n>
- .autoqa-sale-details-item cards
- .autoqa-itemcard-title title
- .autoqa-itemcard-adjudicated-amount amount
- .text-h6.font-weight-bold sale badge
- .bottom span date
- .organization-name seller
- first <a> as lot link

Unlike the reference script, this adapter returns Live, Chrono *and* Catalogue
lots instead of retaining only Live lots.  Persistence/Telegram notifications
remain the responsibility of the parent application.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass(slots=True)
class ReferenceLot:
    title: str
    price_text: str | None
    sale_type: str | None
    status: str
    image_url: str | None
    date_text: str | None
    seller: str | None
    lot_url: str | None
    raw_text: str


def get_new_scraper():
    import cloudscraper

    # Kept intentionally identical to the public reference repository.
    return cloudscraper.create_scraper(
        browser={
            "browser": "firefox",
            "platform": "windows",
            "mobile": False,
        }
    )


def reference_headers(referer: str | None = None) -> dict[str, str]:
    # Header profile from the reference repository.  Do not add Playwright or
    # random UA rotation here: the point of V7 is to stay close to that repo.
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Priority": "u=0, i",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def extract_lots_reference(html_content: str, base_url: str = "https://www.interencheres.com/") -> tuple[list[ReferenceLot], int]:
    """Parse Interencheres cards using the exact selector strategy of the repo.

    Returns ``(lots, raw_card_count)``.  Crucially, the lot URL is taken from
    ``item.select_one('a')`` like the reference project; it is *not* required
    to match a guessed /lot-<id>.html pattern.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    lot_items = soup.select(".autoqa-sale-details-item")
    lots: list[ReferenceLot] = []

    for item in lot_items:
        try:
            title_node = item.select_one(".autoqa-itemcard-title")
            title = title_node.get_text(" ", strip=True) if title_node else "N/A"

            price_node = item.select_one(".autoqa-itemcard-adjudicated-amount .text-md-subtitle-2")
            if not price_node:
                price_node = item.select_one(".autoqa-itemcard-adjudicated-amount")
            price_text = price_node.get_text(" ", strip=True) if price_node else None

            sale_type = None
            status = "Auction continue"
            badge_node = item.select_one(".text-h6.font-weight-bold")
            if badge_node:
                badge_text = badge_node.get_text(" ", strip=True)
                if "Live" in badge_text:
                    sale_type = "Live"
                elif "Catalogue" in badge_text:
                    sale_type = "Catalogue"
                elif "Chrono" in badge_text:
                    sale_type = "Chrono"
                if "Adjugé" in badge_text or "Vendu" in badge_text:
                    status = "Auction completed"

            if price_text and ("Adjugé" in price_text or "Vendu" in price_text):
                status = "Auction completed"

            if sale_type is None:
                if item.select_one(".mdi-timer-sand"):
                    sale_type = "Chrono"
                elif item.select_one(".online--text") and "Live" in item.get_text(" ", strip=True):
                    sale_type = "Live"

            img_node = item.select_one("img")
            img_url = None
            if img_node:
                img_url = str(img_node.get("src") or img_node.get("data-src") or "").strip() or None
                if img_url:
                    img_url = urljoin(base_url, img_url)

            date_node = item.select_one(".bottom span")
            date_text = date_node.get_text(" ", strip=True) if date_node else None

            seller_node = item.select_one(".organization-name span:last-child")
            if not seller_node:
                seller_node = item.select_one(".organization-name")
            seller = seller_node.get_text(" ", strip=True) if seller_node else None

            # Important: identical assumption to the repo: first anchor wins.
            link_node = item.select_one("a")
            lot_url = None
            if link_node and link_node.get("href"):
                lot_url = urljoin(base_url, str(link_node.get("href")))

            lots.append(
                ReferenceLot(
                    title=title,
                    price_text=price_text,
                    sale_type=sale_type,
                    status=status,
                    image_url=img_url,
                    date_text=date_text,
                    seller=seller,
                    lot_url=lot_url,
                    raw_text=item.get_text(" ", strip=True),
                )
            )
        except Exception:
            # Match the forgiving nature of the reference project: one malformed
            # card must not kill the complete page.
            continue

    return lots, len(lot_items)
