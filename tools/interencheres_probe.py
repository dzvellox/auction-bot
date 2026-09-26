"""One-shot real-site probe for the Interencheres repo adapter.

Usage:
    python tools/interencheres_probe.py macbook

It does not touch the DB or Telegram. It prints exactly what the reference
parser sees on page 1 and writes the HTML to interencheres_probe_page1.html for
manual inspection when the site changes its markup.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote_plus

# Même correctif que le probe catégories : autorise l’exécution directe
# `python tools/interencheres_probe.py ...` depuis la racine du projet.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.interencheres_reference import (  # noqa: E402
    extract_lots_reference,
    get_new_scraper,
    reference_headers,
)

query = " ".join(sys.argv[1:]).strip() or "macbook"
url = f"https://www.interencheres.com/recherche/lots?search={quote_plus(query)}&page=1"
scraper = get_new_scraper()
response = scraper.get(url, headers=reference_headers("https://www.interencheres.com/"), timeout=30)
print("HTTP:", response.status_code)
print("URL :", url)
Path("interencheres_probe_page1.html").write_text(response.text, encoding="utf-8", errors="ignore")
if response.status_code != 200:
    raise SystemExit(1)
lots, cards = extract_lots_reference(response.text)
print(".autoqa-sale-details-item:", cards)
print("lots parsés:", len(lots))
for idx, lot in enumerate(lots[:20], 1):
    print(f"{idx:02d}. [{lot.sale_type or '?'}] {lot.title} | {lot.date_text or '-'} | {lot.lot_url or '-'}")
print("HTML sauvé: interencheres_probe_page1.html")
