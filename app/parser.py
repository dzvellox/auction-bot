from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WatchInput:
    query: str
    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    interval_seconds: int | None = None


def parse_watch(text: str) -> WatchInput:
    # Syntaxe: produit | max=1200 | min=200 | condition=used | interval=300
    pieces = [p.strip() for p in text.split("|") if p.strip()]
    if not pieces:
        raise ValueError("Produit manquant")

    result = WatchInput(query=pieces[0])
    for piece in pieces[1:]:
        if "=" not in piece:
            raise ValueError(f"Option invalide: {piece}")
        key, raw = [x.strip() for x in piece.split("=", 1)]
        key = key.lower()
        if key == "max":
            result.max_price = float(raw.replace(",", "."))
        elif key == "min":
            result.min_price = float(raw.replace(",", "."))
        elif key in {"condition", "etat", "état"}:
            value = raw.upper()
            aliases = {"NEUF": "NEW", "NEW": "NEW", "OCCASION": "USED", "USED": "USED"}
            if value not in aliases:
                raise ValueError("condition doit être NEW/NEUF ou USED/OCCASION")
            result.condition = aliases[value]
        elif key in {"interval", "intervalle"}:
            result.interval_seconds = int(raw)
        else:
            raise ValueError(f"Option inconnue: {key}")

    if result.min_price is not None and result.max_price is not None and result.min_price > result.max_price:
        raise ValueError("min ne peut pas être supérieur à max")
    return result
