"""Diagnostic autonome reproduisant la stratégie réseau du repo public.

Usage Windows / PowerShell:
    python tools/interencheres_repo_probe.py macbook

Ne touche ni Telegram ni SQLite. Sauvegarde le HTML de la dernière réponse dans
``interencheres_repo_probe_page1.html`` pour permettre de diagnostiquer un
changement de structure quand le serveur répond HTTP 200.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

# Permet `python tools/interencheres_repo_probe.py ...` depuis la racine.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.interencheres_reference import (  # noqa: E402
    extract_lots_reference,
    get_new_scraper,
    reference_headers,
)


def main() -> int:
    query = " ".join(sys.argv[1:]).strip() or "macbook"
    base_url = "https://www.interencheres.com/"
    url = f"https://www.interencheres.com/recherche/lots?search={quote_plus(query)}&page=1"
    scraper = get_new_scraper()
    max_retries = 2  # valeur du repo upstream

    print(f"Query : {query!r}")
    print(f"URL   : {url}")
    print("Mode  : repo direct (cloudscraper Firefox/Windows + headers upstream)")

    for attempt in range(max_retries + 1):
        print(f"Tentative {attempt + 1}/{max_retries + 1}...")
        try:
            response = scraper.get(
                url,
                headers=reference_headers(base_url),
                timeout=30,
            )
        except Exception as exc:
            print(f"Erreur réseau: {type(exc).__name__}: {exc}")
            if attempt >= max_retries:
                return 2
            time.sleep(5)
            continue

        print("HTTP  :", response.status_code)
        Path("interencheres_repo_probe_page1.html").write_text(
            response.text or "", encoding="utf-8", errors="ignore"
        )

        if response.status_code == 200:
            lots, cards = extract_lots_reference(response.text, base_url)
            print("Cartes .autoqa-sale-details-item :", cards)
            print("Lots parsés                     :", len(lots))
            for idx, lot in enumerate(lots[:30], 1):
                print(
                    f"{idx:02d}. [{lot.sale_type or '?'}] {lot.title} | "
                    f"{lot.price_text or '-'} | {lot.date_text or '-'} | {lot.lot_url or '-'}"
                )
            print("HTML sauvegardé : interencheres_repo_probe_page1.html")
            return 0 if cards else 3

        if response.status_code == 403:
            print("403: renouvellement de session exactement comme le repo upstream.")
            try:
                scraper.cookies.clear()
            except Exception:
                pass
            scraper = get_new_scraper()
            if attempt < max_retries:
                time.sleep(10)
            continue

        if response.status_code == 416:
            print("416: fin de pagination signalée par Interencheres.")
            return 0

        print(f"Statut inattendu {response.status_code}.")
        if attempt < max_retries:
            time.sleep(5)

    print(
        "ECHEC: Interencheres renvoie toujours 403 avec la méthode exacte du repo. "
        "Le blocage intervient avant le parsing HTML."
    )
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
