# V8 — Interencheres sans `/recherche/lots`

Le test repo-direct de V7.1 a confirmé que `sharifulnrv/interencheres-scraper`
reçoit lui aussi HTTP 403 avant le parsing. V8 change donc complètement de
surface d'acquisition au lieu d'ajouter des retries.

## Interencheres

- suppression des appels à `/recherche/lots?search=...` ;
- résolution automatique de catégories via `sitemap.categories.html` ;
- catégories spécialisées pour informatique, composants, smartphones,
  tablettes, consoles, montres, bijoux, vins et véhicules ;
- lecture des pages publiques de catégories puis filtrage local du mot-clé ;
- fallback de parsing sur les liens `/lot-<id>.html` ;
- fallback facultatif sur un vrai Chrome/Edge local via CDP si HTTP est bloqué ;
- aucune résolution automatique de CAPTCHA : une vérification éventuelle doit
  être terminée manuellement dans la fenêtre dédiée ;
- distinction entre prix courant et estimation : une estimation n'est plus
  présentée comme enchère actuelle ;
- rapport détaillé par catégorie et raison réelle de fin de pagination.

## Outils

- `tools/start_interencheres_browser.ps1` / `.bat`
- `tools/interencheres_category_probe.py macbook`
