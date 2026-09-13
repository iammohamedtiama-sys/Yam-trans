# YAM TRANS serveur v4.1

- `/app/` sert la même application YAM TRANS que sur Android : tous les rôles peuvent se connecter depuis un navigateur.
- `/admin-web` redirige vers `/app/`.
- Le Super Super Admin peut ouvrir une société en mode administrateur complet via un token d'impersonation signé.
- Les données existantes restent dans les tables v3 et les entités JSON de synchronisation : aucune suppression/migration destructive.
