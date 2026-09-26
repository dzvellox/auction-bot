from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Quand un script est lancé avec `python tools/xxx.py`, Python ajoute `tools/`
# au sys.path mais pas forcément la racine du projet. Ajoute-la explicitement
# pour que `from app...` fonctionne sous Windows/PowerShell.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.interencheres import InterencheresSource  # noqa: E402


async def main() -> int:
    query = " ".join(sys.argv[1:]).strip() or "macbook"
    source = InterencheresSource()
    watch = SimpleNamespace(query=query, min_price=None, max_price=None)

    print(f"Query : {query!r}")
    print("Mode  : catégories publiques; fallback Chrome/Edge local via CDP")
    print("Route /recherche/lots : DESACTIVEE")
    print()

    # Diagnostic explicite : ne pas laisser croire que la recherche a commencé
    # lorsque le port CDP n'existe pas. Le fetch HTTP direct peut encore réussir,
    # mais en cas de 403 le fallback navigateur aura besoin de cet endpoint.
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1.5) as r:
            import json
            info = json.load(r)
        print(f"CDP   : OK ({info.get('Browser', 'navigateur inconnu')})")
    except Exception:
        print("CDP   : NON DISPONIBLE sur 127.0.0.1:9222")
        print("        Le HTTP direct sera tenté, mais si Interencheres renvoie 403 le probe s'arrêtera.")
    print()
    try:
        categories = await source._resolve_categories(query)
        print("Catégories sélectionnées :")
        for url in categories:
            print(" -", url)
        print()
        items = await source.search(watch)  # type: ignore[arg-type]
    except Exception as exc:
        print(f"ECHEC: {type(exc).__name__}: {exc}")
        print()
        print("Si le message parle du navigateur local :")
        print("  1) tools\\start_interencheres_browser.bat")
        print("  2) termine manuellement toute verification Interencheres dans la fenetre ouverte")
        print("  3) relance cette commande")
        return 2

    print(f"Résultats : {len(items)}")
    for idx, item in enumerate(items[:25], 1):
        price = f"{item.price:.2f} {item.currency}" if item.price is not None else "prix courant non communiqué"
        estimate = f" | estimation {item.estimate_text}" if item.estimate_text else ""
        timing = f" | {item.timing_text}" if item.timing_text else ""
        print(f"{idx:02d}. [{item.auction_type or '?'}] {item.title} | {price}{estimate}{timing}")
        print("    ", item.url)
    print()
    print("Rapport :", source.last_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
