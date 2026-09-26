# V7 — Interencheres: direct adapter of sharifulnrv/interencheres-scraper

- Removed the V6 Interencheres fallback-card heuristics from the active parser.
- Added `app/sources/interencheres_reference.py`, a local reference adapter built
  directly around the selectors and request strategy of
  `github.com/sharifulnrv/interencheres-scraper`.
- Uses `/recherche/lots?search=<query>&page=<n>`.
- Uses `.autoqa-sale-details-item`, `.autoqa-itemcard-title`,
  `.autoqa-itemcard-adjudicated-amount`, `.text-h6.font-weight-bold`,
  `.bottom span`, `.organization-name`, and the first anchor exactly like the
  reference repo.
- No longer requires a lot URL to match a custom URL regex before accepting it.
- No longer re-filters Interencheres cards against the query locally: the
  Interencheres search endpoint is trusted, like the reference scraper.
- Keeps Live, Chrono and Catalogue (the reference script only stores Live).
- Uses the repo-like random 2–5 second delay between pages and 10 seconds after
  a 403 session reset; both are configurable.
- Adds a richer per-source report showing cards found, parsed, retained, pages
  scanned and stop reason.
