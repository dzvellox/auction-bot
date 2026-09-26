# V7.1 — Interencheres repo-direct diagnostic

- Interencheres utilise l'adapter local basé directement sur
  `sharifulnrv/interencheres-scraper`.
- Profil `cloudscraper` identique au repo : Firefox / Windows / non-mobile.
- Headers identiques au repo, y compris `facebookexternalhit`, `Accept-Language`,
  `Priority`, `Sec-Fetch-*` et `Referer` par page.
- Route identique : `/recherche/lots?search=<query>&page=<page>`.
- Sélecteurs principaux identiques au repo.
- Valeur par défaut `INTERENCHERES_MAX_RETRIES=2`, donc 3 essais, comme le repo.
- Délai de 10 s après un 403 et renouvellement complet de session comme le repo.
- Live, Chrono et Catalogue sont conservés (le repo original n'enregistre que Live).
- Ajout de `tools/interencheres_repo_probe.py` pour tester la méthode upstream sans
  Telegram, base de données ni autres sources.
