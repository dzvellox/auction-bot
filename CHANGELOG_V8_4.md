# V8.4

- Le vrai bot privilégie désormais directement le navigateur local CDP lorsque le port 9222 est disponible.
- Suppression des tentatives HTTP Interencheres qui produisaient un 403 avant chaque page.
- Le sitemap HTTP Interencheres est ignoré en mode CDP direct ; la taxonomie statique connue est utilisée.
- Réutilisation d'une seule connexion Playwright/CDP et d'un seul onglet pendant tout le scan.
- Reconnexion automatique uniquement si l'onglet/la connexion CDP devient réellement invalide.
- Réduction configurable du temps de stabilisation et du délai inter-pages en mode CDP direct.
- Logs de progression configurables toutes les N pages.
- Les résultats d’une source sont maintenant mémorisés/notifiés dès que cette source termine, sans attendre toutes les autres sources.
- 21 tests automatisés passent.
