from __future__ import annotations

import asyncio
import logging

from sqlalchemy import delete, select
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import SeenItem, Watch
from app.parser import parse_watch
from app.scanner import Scanner

log = logging.getLogger(__name__)
scanner: Scanner | None = None
scanner_task: asyncio.Task | None = None

HELP = """🤖 <b>Auction Watch Bot</b>

Je surveille plusieurs sites d'enchères et je t'alerte quand une annonce correspond à tes critères.

Sources : eBay, Interencheres (Live + Chrono + Catalogue), Agorastore et Catawiki. Utilise /sources pour voir le backend réellement actif.

<b>Ajouter une veille</b>
<code>/add RTX 4090 | max=1200 | condition=used | interval=300</code>

Options :
• <code>min=</code> prix minimum
• <code>max=</code> prix maximum
• <code>condition=NEW</code> ou <code>USED</code>
• <code>interval=</code> secondes entre deux scans

Commandes :
/add — ajouter une veille
/list — afficher tes veilles
/pause ID — suspendre
/resume ID — reprendre
/delete ID — supprimer
/scan ID — scan manuel + notification des nouvelles annonces
/reset ID — oublier les annonces déjà vues et tout renvoyer
/sources — sources actives
/help — aide
"""


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, parse_mode="HTML")


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    raw = " ".join(context.args).strip()
    if not raw:
        await update.effective_message.reply_text("Exemple : /add RTX 4090 | max=1200 | condition=used | interval=300")
        return
    try:
        data = parse_watch(raw)
        interval = data.interval_seconds or settings.default_scan_interval
        if interval < settings.min_scan_interval:
            raise ValueError(f"interval doit être ≥ {settings.min_scan_interval} secondes")
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return

    with SessionLocal() as db:
        watch = Watch(
            chat_id=chat_id,
            query=data.query,
            min_price=data.min_price,
            max_price=data.max_price,
            condition=data.condition,
            interval_seconds=interval,
        )
        db.add(watch)
        db.commit()
        db.refresh(watch)
        watch_id = watch.id

    await update.effective_message.reply_text(
        f"✅ Veille #{watch_id} créée pour « {data.query} ».\n"
        "Je lance le premier scan et je t’envoie aussi les annonces correspondantes déjà présentes."
    )
    if scanner:
        new_count, notified = await scanner.scan_watch(watch_id, force_notify=True)
        await update.effective_message.reply_text(
            f"🔎 Premier scan terminé : {new_count} annonce(s) nouvelle(s), {notified} notification(s) envoyée(s).\n\n"
            + scanner.report_text(watch_id)
        )


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with SessionLocal() as db:
        rows = list(db.scalars(select(Watch).where(Watch.chat_id == chat_id).order_by(Watch.id)).all())
    if not rows:
        await update.effective_message.reply_text("Tu n'as encore aucune veille.")
        return
    lines = ["📋 Tes veilles :"]
    for w in rows:
        status = "🟢" if w.enabled else "⏸"
        prices = []
        if w.min_price is not None:
            prices.append(f"min {w.min_price:g}€")
        if w.max_price is not None:
            prices.append(f"max {w.max_price:g}€")
        extra = f" — {', '.join(prices)}" if prices else ""
        cond = f" — {w.condition}" if w.condition else ""
        err = " ⚠️" if w.last_error else ""
        lines.append(f"{status} #{w.id} {w.query}{extra}{cond} — {w.interval_seconds}s{err}")
    await update.effective_message.reply_text("\n".join(lines))


def _parse_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not context.args:
        return None
    try:
        return int(context.args[0])
    except ValueError:
        return None


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, enabled: bool) -> None:
    watch_id = _parse_id(context)
    if watch_id is None:
        await update.effective_message.reply_text("ID manquant ou invalide.")
        return
    with SessionLocal() as db:
        watch = db.get(Watch, watch_id)
        if not watch or watch.chat_id != update.effective_chat.id:
            await update.effective_message.reply_text("Veille introuvable.")
            return
        watch.enabled = enabled
        db.commit()
    await update.effective_message.reply_text("▶️ Veille reprise." if enabled else "⏸ Veille suspendue.")


async def pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle(update, context, False)


async def resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle(update, context, True)


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    watch_id = _parse_id(context)
    if watch_id is None:
        await update.effective_message.reply_text("Usage : /delete ID")
        return
    with SessionLocal() as db:
        watch = db.get(Watch, watch_id)
        if not watch or watch.chat_id != update.effective_chat.id:
            await update.effective_message.reply_text("Veille introuvable.")
            return
        # Explicitly clear children so SQLite configurations without FK cascades
        # cannot leave stale SeenItem rows behind if an ID is reused later.
        db.execute(delete(SeenItem).where(SeenItem.watch_id == watch_id))
        db.delete(watch)
        db.commit()
    await update.effective_message.reply_text(f"🗑 Veille #{watch_id} supprimée.")


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    watch_id = _parse_id(context)
    if watch_id is None or scanner is None:
        await update.effective_message.reply_text("Usage : /reset ID")
        return
    with SessionLocal() as db:
        watch = db.get(Watch, watch_id)
        if not watch or watch.chat_id != update.effective_chat.id:
            await update.effective_message.reply_text("Veille introuvable.")
            return
        db.execute(delete(SeenItem).where(SeenItem.watch_id == watch_id))
        watch.initialized = False
        watch.last_scan_at = None
        watch.last_error = None
        db.commit()

    await update.effective_message.reply_text(
        f"♻️ Veille #{watch_id} réinitialisée. Je renvoie les annonces actuellement présentes."
    )
    new_count, notified = await scanner.scan_watch(watch_id, force_notify=True)
    await update.effective_message.reply_text(
        f"🔎 Rescan terminé : {new_count} annonce(s) nouvelle(s), {notified} notification(s) envoyée(s).\n\n"
        + scanner.report_text(watch_id)
    )


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    watch_id = _parse_id(context)
    if watch_id is None or scanner is None:
        await update.effective_message.reply_text("Usage : /scan ID")
        return
    with SessionLocal() as db:
        watch = db.get(Watch, watch_id)
        if not watch or watch.chat_id != update.effective_chat.id:
            await update.effective_message.reply_text("Veille introuvable.")
            return
    new_count, notified = await scanner.scan_watch(watch_id, force_notify=True)
    await update.effective_message.reply_text(
        f"🔎 Scan terminé : {new_count} nouvelle(s), {notified} notification(s).\n\n"
        + scanner.report_text(watch_id)
    )


async def sources_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if scanner is None:
        await update.effective_message.reply_text("Scanner non démarré.")
        return
    names = scanner.source_names
    text = "🌐 Sources actives :\n" + ("\n".join(f"• {name}" for name in names) if names else "Aucune")
    await update.effective_message.reply_text(text)


async def post_init(application: Application) -> None:
    global scanner, scanner_task
    scanner = Scanner(application.bot)
    scanner_task = asyncio.create_task(scanner.loop(), name="auction-scanner")


async def post_shutdown(application: Application) -> None:
    global scanner, scanner_task
    if scanner:
        await scanner.close()
    if scanner_task:
        try:
            await scanner_task
        except asyncio.CancelledError:
            pass


def run() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    init_db()
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler(["start", "help"], start_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("pause", pause_cmd))
    app.add_handler(CommandHandler("resume", resume_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("sources", sources_cmd))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
