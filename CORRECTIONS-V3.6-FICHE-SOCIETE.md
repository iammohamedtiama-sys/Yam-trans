# Serveur Yam-Trans v3.6 — Administration détaillée des sociétés

Nouveaux endpoints réservés au `platform_admin` :

- `GET /api/v2/platform/companies/{company_id}` : fiche complète, utilisateurs, statistiques, recettes et opérations.
- `PUT /api/v2/platform/companies/{company_id}/users/{user_id}` : modification d'un utilisateur et réinitialisation facultative du mot de passe.

Le mot de passe reste stocké sous forme de hash PBKDF2 et n'est jamais retourné par l'API.
