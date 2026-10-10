# YAM TRANS Serveur/Web v4.4 — Opérations et administration

- Endpoint plateforme réservé à `platform_admin` pour modifier/annuler Courrier et Bagages.
- Annulation logique : données conservées, statut Annulé, montant exclu des statistiques.
- Version serveur de l’entité incrémentée afin de protéger l’annulation contre les anciens caches clients.
- Statistiques Courrier basées sur le montant unique `fee`.
- Statistiques Bagages basées sur le montant unique `paid`.
- API société pour modifier un utilisateur, réinitialiser son mot de passe, changer rôle/agence/modules et activer/désactiver son compte.
- Aucun hard-delete utilisateur dans le workflow d’administration.
- Frontend Web synchronisé avec l’interface Android v4.4 et ses routes métier existantes.

Version API : 4.4.0.
