from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from app.sources.base import AuctionItem


def _fmt_remaining(end_time: datetime | None) -> str:
    if not end_time:
        return "inconnue"
    now = datetime.now(timezone.utc)
    end = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)
    seconds = int((end - now).total_seconds())
    if seconds <= 0:
        return "terminée"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} j {hours} h"
    return f"{hours} h {minutes} min"


def _timing_lines(item: AuctionItem) -> str:
    kind = f"\n🏷 Type : <b>{escape(item.auction_type)}</b>" if item.auction_type else ""
    if item.timing_text:
        label = "📅 Vente" if item.auction_type in {"Live", "Catalogue"} else "⏳ Clôture"
        return f"{kind}\n{label} : <b>{escape(item.timing_text)}</b>"
    if item.start_time:
        return f"{kind}\n📅 Vente : <b>{escape(item.start_time.isoformat(sep=' ', timespec='minutes'))}</b>"
    if item.end_time:
        return f"{kind}\n⏳ Fin dans : <b>{escape(_fmt_remaining(item.end_time))}</b>"
    return kind


def format_auction(item: AuctionItem, watch_id: int) -> str:
    price = "prix non communiqué"
    if item.price is not None:
        price = f"{item.price:.2f} {escape(item.currency or '')}".strip()
    price_label = escape(item.price_label or "Prix actuel")
    estimate = f"\n📈 Estimation : <b>{escape(item.estimate_text)}</b>" if item.estimate_text else ""
    bids = f"\n👥 Enchères : {item.bid_count}" if item.bid_count is not None else ""
    condition = f"\n📦 État : {escape(item.condition)}" if item.condition else ""
    timing = _timing_lines(item)
    return (
        f"🔔 <b>Enchère détectée</b>\n\n"
        f"<b>{escape(item.title)}</b>\n"
        f"💰 {price_label} : <b>{price}</b>"
        f"{estimate}{bids}{condition}{timing}\n"
        f"🌐 Source : {escape(item.source)}\n"
        f"🔎 Veille #{watch_id}\n\n"
        f"<a href=\"{escape(item.url, quote=True)}\">Voir l'enchère</a>"
    )
