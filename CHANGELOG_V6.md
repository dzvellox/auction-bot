# V6 — sources fiables, prix Catawiki et diagnostic par site

Cette version corrige le cas où une veille comme `/add macbook` ne remontait pratiquement que Catawiki.

## Interencheres

- `INTERENCHERES_MAX_PAGES=100` est maintenant clairement traité comme une **borne maximale**, pas comme un nombre de pages artificiellement forcé.
- Le rapport indique exactement pourquoi le crawl s'arrête : limite atteinte, HTTP 416 (fin réelle), pages vides consécutives ou indisponibilité réseau.
- Le parseur ne dépend plus uniquement de `.autoqa-sale-details-item`.
- Fallback sur les liens stables `/lot-<id>.html` lorsque la structure des cartes change.
- Live, Chrono et Catalogue sont conservés.
- `Prix actuel`, `Enchère actuelle`, `Mise à prix` et `Prix de départ` sont différenciés.
- Les estimations ne sont pas utilisées comme faux prix courant.

## Catawiki

- Correction des prix affichés sous la forme `€ 97` (devise avant le montant).
- Le prix vient prioritairement de la **page détail du lot** et du champ `Offre actuelle` / `Current bid`.
- Une estimation n'est plus prise pour l'enchère actuelle lorsqu'il n'y a encore aucune offre.
- Le message Telegram affiche maintenant le vrai libellé, par exemple `Offre actuelle`.

## Agorastore

- Le frontend actuel étant fortement dynamique, la recherche bascule sur un navigateur Playwright lorsque le HTML HTTP est seulement une coquille SPA.
- Recherche via le champ visible du site, puis récupération des URLs de produits actuelles `.../agora-<id>`.
- Les pages détail sont rendues pour récupérer `Enchère actuelle`, `Prix de départ` et la fin de vente.

## Telegram / diagnostic

Après `/add`, `/scan` et `/reset`, le bot renvoie désormais un détail par source, par exemple :

```text
📊 Détail par source :
• interencheres (cloudscraper + fallback lots) : 4 résultat(s) — pages 28/100, lots bruts 560, correspondances 4 — fin réelle signalée par Interencheres (HTTP 416) à la page 29
• agorastore (rendu navigateur SPA) : 1 résultat(s) — 1 annonce candidate, 1 retenue, 1 prix exact, méthode=recherche UI
• catawiki (prix détaillé) : 12 résultat(s) — 12 lots candidats, 12 retenus, 12 prix courants exacts
```

Cela permet de distinguer immédiatement :

- une source réellement vide ;
- une source qui a fini sa pagination avant 100 pages ;
- une source bloquée/indisponible ;
- un problème de parsing ;
- le nombre de prix réellement extraits.

## Tests

16 tests automatisés couvrent notamment :

- prix `100 €` et `€ 100` ;
- fallback Interencheres sans ancien wrapper HTML ;
- Live / Chrono / Catalogue ;
- fin de pagination HTTP 416 ;
- prix courant Catawiki distinct de l'estimation ;
- Catawiki sans enchère actuelle ;
- prix Agorastore étiqueté ;
- filtrage de prix.
