# V4

- suppression complète des requêtes Interencheres `/recherche?...` responsables des 403 ;
- suppression du fallback Playwright Interencheres qui répétait inutilement le blocage ;
- backend Interencheres JSON optionnel via Apify ;
- fallback Interencheres sur pages publiques sans contournement anti-bot ;
- `/sources` indique `JSON via Apify` ou `pages publiques, mode limité` ;
- prise en charge des ventes Live à date/heure précise via `saleDatetime` ;
- conservation du premier scan avec notifications immédiates ;
- conservation de `/reset ID` ;
- 7 tests passent.
