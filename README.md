# Auction Watch Bot V8.4 — Telegram + eBay + Interencheres + Agorastore + Catawiki

Bot Telegram de veille d'enchères. Une commande comme :

```text
/add macbook | interval=300
```

lance immédiatement une recherche sur toutes les sources **réellement actives**, envoie les annonces correspondantes déjà présentes, les mémorise dans SQLite, puis surveille les nouvelles annonces.

## Sources

- **eBay** — Browse API officielle, enchères uniquement. Nécessite `EBAY_CLIENT_ID` et `EBAY_CLIENT_SECRET`.
- **Interencheres** — catégories publiques + navigateur Chrome/Edge local via CDP, avec Live / Chrono / Catalogue et fallback sur les liens stables `/lot-<id>.html`. La route protégée `/recherche/lots` n'est plus utilisée.
- **Agorastore** — recherche HTTP puis rendu Playwright du frontend SPA lorsque nécessaire.
- **Catawiki** — recherche des lots puis lecture de chaque page détail pour récupérer l'`Offre actuelle` / `Current bid` plutôt qu'une estimation.

Utilise `/sources` pour vérifier les backends chargés.

## Correctifs V6 importants

### 1. `INTERENCHERES_MAX_PAGES=100`

`100` signifie **jusqu'à 100 pages**. Si Interencheres indique qu'il n'existe plus de page utile avant, le bot s'arrête au lieu de requêter artificiellement des pages inexistantes.

Par exemple, si la page 29 renvoie HTTP 416 :

```text
pages 28/100 ... fin réelle signalée par Interencheres (HTTP 416) à la page 29
```

Le bot affiche désormais cette raison dans le diagnostic Telegram.

Le bug important de V5 était différent : le bot pouvait compter des liens de lots mais ne rien extraire si la classe HTML `.autoqa-sale-details-item` avait changé. V6 récupère aussi directement les URLs stables `/lot-<id>.html`.

### 2. Prix Catawiki

V6 prend en charge les deux écritures :

```text
97 €
€ 97
```

Surtout, le bot recherche le champ sémantique :

```text
Offre actuelle
€ 97
```

et ne transforme plus ceci :

```text
Offre actuelle
Aucune offre
Estimation € 450 - € 550
```

en faux prix courant de 450 €.

### 3. Agorastore

Le site peut renvoyer une page HTTP `200` qui ne contient encore que l'application JavaScript. V6 ne considère plus automatiquement cela comme « zéro résultat » : il ouvre le site avec Playwright, utilise le champ de recherche visible et rend les pages détail.

### 4. Diagnostic par source

Après `/add`, `/scan` ou `/reset`, tu obtiens maintenant :

```text
📊 Détail par source :
• interencheres (...) : 3 résultat(s) — pages 28/100 ...
• agorastore (...) : 1 résultat(s) — ... méthode=recherche UI
• catawiki (...) : 8 résultat(s) — ... 8 prix courant(s) exact(s)
```

Ainsi, si `/add macbook` retourne uniquement Catawiki, tu vois immédiatement si Interencheres a réellement trouvé 0 lot, si la source a été bloquée ou si sa pagination s'est terminée.

## Installation Windows 10/11

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Copie `.env.example` vers `.env` et renseigne au minimum :

```env
TELEGRAM_BOT_TOKEN=123456789:TON_TOKEN
```

### Configuration recommandée

```env
ENABLE_EBAY=true
ENABLE_INTERENCHERES=true
ENABLE_AGORASTORE=true
ENABLE_CATAWIKI=true

INTERENCHERES_MAX_PAGES=100
INTERENCHERES_MAX_RETRIES=2
INTERENCHERES_TIMEOUT_SECONDS=30
INTERENCHERES_PAGE_DELAY_SECONDS=0.8
INTERENCHERES_EMPTY_PAGE_TOLERANCE=2

CATAWIKI_MAX_RESULTS=40
CATAWIKI_DETAIL_CONCURRENCY=4

AGORASTORE_MAX_RESULTS=40
AGORASTORE_DETAIL_CONCURRENCY=3

ENABLE_BROWSER_FALLBACK=true
BROWSER_HEADLESS=true
BROWSER_CHANNEL=msedge
BROWSER_TIMEOUT_MS=30000
```

### eBay

Sans clés eBay :

```env
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
```

la source eBay est **ignorée**. Le bot ne peut donc pas trouver « sur tous les sites » si `/sources` ne montre pas eBay.

## Lancement

```powershell
python main.py
```

## Commandes

```text
/add macbook | interval=300
/add RTX 5070 | max=700 | interval=300
/list
/sources
/scan 1
/reset 1
/pause 1
/resume 1
/delete 1
/help
```

### Ancienne veille créée avant V6

Si une ancienne version a déjà mémorisé des annonces sans te les envoyer correctement :

```text
/reset ID
```

Exemple :

```text
/reset 1
```

Cela vide uniquement les annonces déjà vues de cette veille et relance la recherche immédiatement.

## Prix Telegram

Le message utilise maintenant le type de prix réellement détecté :

```text
💰 Offre actuelle : 97.00 EUR
```

ou :

```text
💰 Prix de départ : 50.00 EUR
```

ou, lorsqu'aucun vrai prix n'est publié :

```text
💰 Prix actuel : prix non communiqué
```

## Tests

```powershell
$env:PYTHONPATH="."
$env:TELEGRAM_BOT_TOKEN="dummy"
python -m pytest -q
```

État de la V6 : **16 tests passent**.

## Architecture

```text
Telegram
   │
   ▼
Scanner
   ├── eBay ─────────────── API officielle
   ├── Interencheres ────── cloudscraper + fallback /lot-<id>.html
   ├── Agorastore ───────── HTTP + Playwright SPA
   └── Catawiki ─────────── recherche + détail de chaque lot
   │
   ▼
Normalisation AuctionItem
   ├── prix sémantique
   ├── Live / Chrono / Catalogue
   ├── date / clôture
   └── URL stable
   │
   ▼
SQLite anti-doublons
   │
   ▼
Telegram + diagnostic par source
```

## Crédit technique Interencheres

Le connecteur reste inspiré du dépôt MIT :

`https://github.com/sharifulnrv/interencheres-scraper`

V6 ne copie pas son comportement « Live uniquement » : le bot conserve Live, Chrono et Catalogue et ajoute ses propres filtres, diagnostics, fallback de structure HTML et intégration asynchrone.

## Interencheres V7: mode repo direct

The Interencheres connector now follows `github.com/sharifulnrv/interencheres-scraper`
as directly as possible instead of trying to infer alternative card layouts.
It uses the same public search route, `cloudscraper`, header profile and primary
CSS selectors. The only product-level changes are: all three sale types are
kept (Live, Chrono, Catalogue), the results are converted to the bot's common
model, and the scraper stops after a finite scan rather than looping forever.

Recommended `.env` values:

```env
INTERENCHERES_MAX_PAGES=100
INTERENCHERES_MAX_RETRIES=2
INTERENCHERES_TIMEOUT_SECONDS=30
INTERENCHERES_PAGE_DELAY_MIN_SECONDS=2
INTERENCHERES_PAGE_DELAY_MAX_SECONDS=5
INTERENCHERES_BLOCKED_RETRY_DELAY_SECONDS=10
INTERENCHERES_RETRY_DELAY_SECONDS=5
```

`INTERENCHERES_PAGE_DELAY_SECONDS` is kept only for backward compatibility and
is no longer used by the V7 repo adapter.


### Diagnostic Interencheres — méthode exacte du repo

Avant de lancer tout le bot, tu peux vérifier uniquement Interencheres :

```powershell
python tools/interencheres_repo_probe.py macbook
```

Le script utilise la même route, le même profil `cloudscraper`, les mêmes headers,
le même `Referer`, les mêmes 2 retries et le même délai de 10 secondes après un
403 que `sharifulnrv/interencheres-scraper`. Il n'utilise ni Telegram, ni SQLite,
ni Playwright.

- `HTTP 200` + des cartes : le repo fonctionne sur ta connexion, donc le bot doit
  pouvoir les convertir.
- `HTTP 200` + 0 carte : la structure HTML du site a changé. Le fichier HTML est
  sauvegardé pour diagnostic.
- `HTTP 403` après les retries : la méthode du repo elle-même est bloquée par
  Interencheres sur cette connexion/IP. Dans ce cas changer les sélecteurs HTML
  ne peut rien résoudre, puisque le HTML des résultats n'est jamais reçu.

---

## Interencheres V8 — important

Le probe V7.1 a démontré que la méthode exacte du dépôt
`sharifulnrv/interencheres-scraper` peut désormais recevoir **HTTP 403 avant le
parsing HTML**. La V8 n'utilise donc plus du tout `/recherche/lots`.

Elle sélectionne des **pages publiques de catégories** depuis le sitemap
Interencheres, récupère les cartes de lots et applique le mot-clé localement.
Par exemple `macbook` privilégie `ordinateurs-portables-et-fixes`, tandis que
`RTX 5070` privilégie `peripheriques-et-composants-informatiques`.

Si les requêtes HTTP ordinaires sont elles aussi refusées, utilise le navigateur
local :

```powershell
.\tools\start_interencheres_browser.ps1
```

Une fenêtre Chrome/Edge dédiée s'ouvre. Si le site affiche une vérification,
termine-la **manuellement** puis garde la fenêtre ouverte. Le bot se connecte à
ce navigateur via `INTERENCHERES_CDP_URL=http://127.0.0.1:9222`.

Teste ensuite sans Telegram :

```powershell
python tools/interencheres_category_probe.py macbook
python tools/interencheres_category_probe.py "RTX 5070"
```

Le bot ne tente pas de résoudre ou contourner automatiquement un CAPTCHA.

Une page de catégorie peut utiliser un chargement infini et ignorer `?page=N`.
Dans ce cas le rapport indique explicitement `pagination HTML répétée` et
s'arrête, même si `INTERENCHERES_MAX_PAGES=100`. `100` est une limite haute,
pas un nombre artificiel de pages à forcer.

Quand Interencheres n'affiche qu'une estimation, Telegram montre désormais :

```text
💰 Prix actuel : prix non communiqué
📈 Estimation : 120 € - 320 €
```

au lieu de faire passer l'estimation pour une enchère en cours.

## V8.2 — vérifier le navigateur Interencheres

Sous Windows, le fait que Chrome affiche Interencheres ne prouve pas que le port CDP est actif. Le lanceur V8.2 vérifie désormais réellement le port 9222.

```powershell
.\tools\start_interencheres_browser.ps1
```

Ne continue que si le script affiche :

```text
CDP OK : http://127.0.0.1:9222/json/version
```

Diagnostic indépendant :

```powershell
python tools/interencheres_cdp_check.py
```

Puis :

```powershell
python tools/interencheres_category_probe.py macbook
```


## V8.3 — pages Interencheres lentes

Si le navigateur local fonctionne mais qu'une catégorie devient lente après plusieurs dizaines de pages, V8.3 ne dépend plus de `locator("body")`. Le HTML déjà chargé est parsé directement et la page est retentée si elle est réellement vide/incomplète.

Variables facultatives :

```env
INTERENCHERES_BROWSER_PAGE_RETRIES=2
INTERENCHERES_BROWSER_RETRY_DELAY_SECONDS=1.0
```


## V8.4 — mode CDP direct dans le vrai bot

Le probe V8.3 a confirmé que le navigateur local trouve bien les lots Interencheres. Le vrai bot utilisait toutefois encore l'ancien schéma `httpx -> 403 -> CDP` pour chaque page. Cela produisait beaucoup de logs `403` et ralentissait fortement un scan de plusieurs dizaines de pages.

V8.4 change ce comportement :

- si `http://127.0.0.1:9222/json/version` répond, Interencheres utilise **directement** le navigateur local ;
- aucun appel HTTP Interencheres n'est tenté pour les pages de catégories pendant ce scan ;
- le sitemap HTTP n'est pas interrogé lorsque le mode CDP direct est actif ;
- une seule connexion Playwright/CDP et un seul onglet sont réutilisés pendant tout le scan ;
- la fenêtre Chrome/Edge de l'utilisateur reste ouverte après le scan ;
- un log de progression est produit toutes les 10 pages par défaut.

Réglages conseillés :

```env
INTERENCHERES_PREFER_CDP=true
INTERENCHERES_CDP_URL=http://127.0.0.1:9222
INTERENCHERES_CDP_DIRECT_SETTLE_MS=350
INTERENCHERES_CDP_DIRECT_PAGE_DELAY_SECONDS=0.05
INTERENCHERES_PROGRESS_EVERY_PAGES=10
```

Au démarrage d'un scan Interencheres avec le navigateur prêt, le log attendu est :

```text
interencheres: navigateur CDP détecté; mode direct activé (aucun essai HTTP sur les pages Interencheres)
```

Les lignes `HTTP 403 ... bascule navigateur local CDP` ne doivent alors plus apparaître pour chaque page.


### Notifications plus tôt

Le scanner V8.4 traite maintenant chaque source dès qu'elle termine. Par exemple, si Interencheres a trouvé des lots, ils sont enregistrés et envoyés sur Telegram avant de lancer/attendre la fin d'Agorastore et Catawiki.
