# V8.3 — Interencheres CDP stable

- Suppression du `locator("body").inner_text(timeout=5000)` qui produisait de faux échecs après de nombreuses pages.
- Détection anti-bot basée sur le HTML déjà récupéré, sans attendre un locator Playwright.
- Une navigation CDP lente peut désormais être acceptée si le HTML utile est déjà chargé.
- Jusqu’à 2 retries de page configurables (`INTERENCHERES_BROWSER_PAGE_RETRIES`).
- Les erreurs distinguent maintenant navigateur CDP réellement injoignable et simple page lente.
- Nettoyage des titres fallback: retrait de `Déjà vu`, `Estimation : ...` et numéro de lot UI en tête.
- Le probe affiche aussi la date/heure/clôture quand Interencheres la fournit.
