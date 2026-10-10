# Serveur Yam-Trans v3.5

- L’endpoint `PUT /api/v2/admin/companies/{company_id}` accepte désormais les champs de branding et de suivi : couleurs, titre, sous-titre, email support, site web et image de couverture.
- Le logo reste remplacé via l’endpoint d’upload dédié.
- Le code société n’est pas modifiable pour protéger les identifiants, la synchronisation et les URLs de suivi existantes.
