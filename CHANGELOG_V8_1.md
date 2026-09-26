# V8.1 — correctif des outils de diagnostic

- Corrige `ModuleNotFoundError: No module named app` quand les probes sont lancés directement sous Windows avec `python tools/...py`.
- Ajoute explicitement la racine du projet à `sys.path` dans `interencheres_category_probe.py` et `interencheres_probe.py`.
- Aucun changement de logique du bot ou du connecteur Interencheres.
- La commande recommandée reste `python tools/interencheres_category_probe.py macbook`.
