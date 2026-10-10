# Validation YAM TRANS Serveur/Web v4.5.0

Validation finale effectuée le 13/09/2026.

- `frontend/src/main.js` : syntaxe JavaScript valide (`node --check`).
- `app/main.py` : compilation Python valide (`py_compile`).
- `/health` retourne la version 4.5.0.
- Test d'intégration FastAPI/SQLite : connexion société et plateforme OK.
- Anti-doublon Courrier : le premier envoi est accepté, le second identique du même appareil dans la fenêtre de sécurité est refusé.
- Restriction de destination par agence testée côté serveur.
- Annulation Courrier/Bagage refusée à l'admin société et autorisée au `platform_admin` uniquement.
- Un Courrier déjà rattaché à un bordereau peut être annulé uniquement par le Super Super Admin, avec conservation de la trace du manifeste.
- Les archives de livraison excluent les caches, `node_modules`, `dist`, `.gradle`, `build`, `__pycache__` et les fichiers de sauvegarde de développement.
