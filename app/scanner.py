from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from telegram import Bot

from app.config import settings
from app.db import SessionLocal
from app.formatting import format_auction
from app.models import SeenItem, Watch
from app.sources import AgorastoreSource, CatawikiSource, EbaySource, InterencheresSource
from app.sources.base import SourceUnavailableError

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.sources = []
        if settings.enable_ebay and settings.ebay_client_id and settings.ebay_client_secret:
            self.sources.append(EbaySource())
        elif settings.enable_ebay:
            log.warning("eBay activé mais EBAY_CLIENT_ID/EBAY_CLIENT_SECRET absents: source ignorée")
        if settings.enable_interencheres:
            self.sources.append(InterencheresSource())
        if settings.enable_agorastore:
            self.sources.append(AgorastoreSource())
        if settings.enable_catawiki:
            self.sources.append(CatawikiSource())
        self._stop = asyncio.Event()
        self._last_source_stats: dict[int, list[dict[str, object]]] = {}

    @property
    def source_names(self) -> list[str]:
        return [getattr(s, "status_label", getattr(s, "name", s.__class__.__name__.replace("Source", "").lower())) for s in self.sources]


    def report_text(self, watch_id: int) -> str:
        rows = self._last_source_stats.get(watch_id, [])
        if not rows:
            return "Aucun détail de source disponible pour ce scan."
        lines = ["📊 Détail par source :"]
        for row in rows:
            name = str(row.get("label") or row.get("source") or "source")
            count = int(row.get("count") or 0)
            error = row.get("error")
            report = str(row.get("report") or "").strip()
            if error:
                lines.append(f"• ❌ {name} : indisponible — {error}")
            elif report:
                lines.append(f"• {name} : {count} résultat(s) — {report}")
            else:
                lines.append(f"• {name} : {count} résultat(s)")
        return "\n".join(lines)

    async def close(self) -> None:
        self._stop.set()
        await asyncio.gather(*(s.close() for s in self.sources), return_exceptions=True)

    async def scan_watch(self, watch_id: int, force_notify: bool = False) -> tuple[int, int]:
        with SessionLocal() as db:
            watch = db.get(Watch, watch_id)
            if not watch:
                return (0, 0)
            watch_snapshot = watch
            initialized_before = watch.initialized

        errors: list[str] = []
        source_stats: list[dict[str, object]] = []
        new_count = 0
        notified = 0

        async def process_items(items) -> tuple[int, int]:
            local_new = 0
            local_notified = 0
            for item in items:
                if not item.external_id:
                    continue
                with SessionLocal() as db:
                    exists = db.scalar(
                        select(SeenItem.id).where(
                            SeenItem.watch_id == watch_id,
                            SeenItem.source == item.source,
                            SeenItem.external_id == item.external_id,
                        )
                    )
                    if exists:
                        continue
                    row = SeenItem(
                        watch_id=watch_id,
                        source=item.source,
                        external_id=item.external_id,
                        title=item.title,
                        url=item.url,
                        price=item.price,
                        currency=item.currency,
                        end_time=item.end_time.replace(tzinfo=None) if item.end_time and item.end_time.tzinfo else item.end_time,
                    )
                    db.add(row)
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        continue
                local_new += 1

                should_notify = force_notify or initialized_before or settings.notify_existing_on_first_scan
                if should_notify:
                    try:
                        await self.bot.send_message(
                            chat_id=watch_snapshot.chat_id,
                            text=format_auction(item, watch_id),
                            parse_mode="HTML",
                            disable_web_page_preview=False,
                        )
                        local_notified += 1
                        await asyncio.sleep(0.06)
                    except Exception:
                        log.exception("Telegram notification failed for watch %s", watch_id)
            return local_new, local_notified

        # V8.4: process each source immediately instead of waiting for every
        # source to finish.  A long Interencheres/Agorastore/Catawiki scan no
        # longer delays notifications already found by a previous source.
        for source in self.sources:
            source_name = getattr(source, "name", source.__class__.__name__)
            source_label = getattr(source, "status_label", source_name)
            try:
                items = await source.search(watch_snapshot)
                report = str(getattr(source, "last_report", "") or "").strip()
                source_stats.append({
                    "source": source_name,
                    "label": source_label,
                    "count": len(items),
                    "report": report,
                    "error": None,
                })
                log.info("watch=%s source=%s items=%s report=%s", watch_id, source_name, len(items), report)

                src_new, src_notified = await process_items(items)
                new_count += src_new
                notified += src_notified
                if src_new or src_notified:
                    log.info(
                        "watch=%s source=%s processed immediately new=%s notified=%s",
                        watch_id, source_name, src_new, src_notified,
                    )
            except SourceUnavailableError as exc:
                msg = str(exc)[:500]
                errors.append(f"{source_name}: {msg}")
                source_stats.append({
                    "source": source_name,
                    "label": source_label,
                    "count": 0,
                    "report": str(getattr(source, "last_report", "") or "").strip(),
                    "error": msg,
                })
                log.warning("Source unavailable watch=%s source=%s — %s", watch_id, source_name, exc)
            except Exception as exc:
                msg = str(exc)[:500]
                errors.append(f"{source_name}: {msg}")
                source_stats.append({
                    "source": source_name,
                    "label": source_label,
                    "count": 0,
                    "report": str(getattr(source, "last_report", "") or "").strip(),
                    "error": msg,
                })
                log.exception("Scan failed for watch %s on %s", watch_id, source_name)
            self._last_source_stats[watch_id] = list(source_stats)
            await asyncio.sleep(0.15)

        self._last_source_stats[watch_id] = source_stats

        with SessionLocal() as db:
            watch = db.get(Watch, watch_id)
            if watch:
                watch.initialized = True
                watch.last_scan_at = datetime.utcnow()
                watch.last_error = "\n".join(errors)[:2000] if errors else None
                db.commit()
        return new_count, notified

    async def loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.utcnow()
            with SessionLocal() as db:
                watches = list(db.scalars(select(Watch).where(Watch.enabled.is_(True))).all())

            for watch in watches:
                due = watch.last_scan_at is None or (now - watch.last_scan_at).total_seconds() >= watch.interval_seconds
                if due:
                    await self.scan_watch(watch.id)
                    await asyncio.sleep(0.25)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
