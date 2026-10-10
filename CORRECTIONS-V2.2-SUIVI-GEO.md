# Yam-Trans Serveur 2.2 — Suivi premium & géolocalisation

## Page publique de suivi
- Nouvelle interface responsive orientée mobile.
- Timeline étape par étape : dépôt, préparation, expédition, arrivée, disponibilité, livraison.
- Les dates proviennent des événements logistiques réels synchronisés par les clients.
- Affichage du trajet départ → destination et du statut courant.
- Nom du destinataire toujours masqué et aucune donnée financière/téléphone/pièce d'identité exposée.

## Point de retrait
- La page retrouve l'agence de destination synchronisée.
- Affiche le nom du point de retrait, l'adresse et l'indication pratique.
- Carte Google Maps intégrée à partir des coordonnées ou de l'adresse.
- Bouton externe « Ouvrir l'itinéraire Google Maps ».

## API
- `/api/v1/track/{code}` retourne désormais l'historique public sécurisé `events` pour le suivi étape par étape.
- Version API : 2.2.0.
