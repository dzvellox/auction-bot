# V8.2 — correctif lanceur CDP Windows

- Le lanceur ne suppose plus que `--remote-debugging-port=9222` fonctionne : il vérifie réellement `http://127.0.0.1:9222/json/version`.
- Fermeture ciblée d'un ancien Chrome/Edge utilisant uniquement le profil `.interencheres-browser-profile`, car un ancien processus pouvait absorber le nouvel appel et ignorer les flags CDP.
- Ajout de `--remote-debugging-address=127.0.0.1` et `--new-window`.
- Tentative automatique avec Chrome puis Edge si le premier navigateur n'expose pas le port.
- Nouveau diagnostic `python tools/interencheres_cdp_check.py`.
- Le probe affiche désormais explicitement `CDP : OK` ou `CDP : NON DISPONIBLE` avant le scan.
