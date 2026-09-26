# V5 — Interencheres local via cloudscraper

## Interencheres

- Suppression complète du backend Apify et de ses variables d'environnement.
- Nouveau connecteur local inspiré de `sharifulnrv/interencheres-scraper` (MIT).
- Route utilisée : `https://www.interencheres.com/recherche/lots?search=<query>&page=<n>`.
- Utilisation de `cloudscraper` + `BeautifulSoup`.
- Support des cartes `.autoqa-sale-details-item`.
- Support **Live + Chrono + Catalogue** (le dépôt de référence ne conservait que Live).
- Pagination bornée (`INTERENCHERES_MAX_PAGES`, défaut 10).
- Session renouvelée en cas de 403/429, avec nombre de tentatives borné.
- Le scraper synchrone tourne dans `asyncio.to_thread()` afin de ne pas bloquer Telegram.
- Les lots déjà adjugés/vendus sont ignorés.
- Les estimations ne sont pas présentées comme prix courant.

## Configuration

Nouvelles variables :

```env
INTERENCHERES_MAX_PAGES=10
INTERENCHERES_MAX_RETRIES=2
INTERENCHERES_TIMEOUT_SECONDS=30
INTERENCHERES_PAGE_DELAY_SECONDS=0.8
```

`INTERENCHERES_APIFY_TOKEN`, `INTERENCHERES_APIFY_MAX_ITEMS` et `INTERENCHERES_APIFY_TIMEOUT_SECONDS` ne sont plus utilisés.
