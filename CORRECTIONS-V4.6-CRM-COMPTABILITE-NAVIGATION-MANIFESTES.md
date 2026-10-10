# YAM TRANS v4.6.0 — CRM, fidélité, comptabilité, navigation et QR manifestes

## Navigation Android
- Le bouton Retour physique Android revient à l'interface précédente de YAM TRANS au lieu de fermer immédiatement l'application.
- Les modales se ferment en priorité, puis l'historique interne est dépilé, puis le tableau de bord du module, puis l'écran des activités.

## Rapports Courrier
- Le nombre total d'envois est affiché explicitement dans le rapport et dans le PDF.
- La tuile « Annulés » n'est affichée que lorsqu'il existe au moins une opération annulée.
- Signatures adaptatives : agent + caissier si filtre agent, chef d'agence + caissier si filtre agence, responsable exploitation + caissier pour un rapport global.

## Comptabilité Courrier
- Présentation professionnelle avec Recettes totales, Dépenses totales et Net à verser.
- Journal chronologique entrée/sortie avec référence, agence, agent/caissier et solde.
- Les opérations annulées restent traçables mais ne sont pas intégrées aux recettes.
- PDF A4 professionnel avec signatures caissier et chef d'agence.

## CRM Clients
- Une identité client commune est alimentée par Courrier, Bagages et Tickets.
- Écrans Clients Courrier, Clients Bagages et Clients Tickets.
- Recherche avancée par identité, localisation, date d'inscription, points, statut et activité.
- Fiche client enrichie : historique, montants, activité par service, moyenne, destinations, agences, évolution mensuelle et niveau fidélité.
- Depuis la fiche, un client peut être utilisé directement pour un nouvel envoi, un nouveau bagage ou un nouveau billet.
- Création et modification de fiche client.
- Export CSV des clients pour campagnes marketing.
- Sélection multiple et envoi SMS depuis l'application via la configuration SMS de la société.

## Fidélité
- Niveaux Bronze, Argent, Or et Platine.
- Points, activité, dépenses et accès direct à la fiche client complète.
- Filtres par client, niveau et minimum de points.
- Conservation du mode séparé Courrier/Tickets ou portefeuille commun.

## Bordereaux et manifestes
- Le bordereau Courrier conserve son numéro unique et reçoit un QR imprimé dans les PDF/impressions.
- Le manifeste Bagages possède un numéro MBG unique/stable et un QR.
- Le scan d'un QR de bordereau/manifeste ouvre directement la liste correspondante.
- Depuis cette liste : confirmation départ/arrivée selon le document.
- La confirmation d'arrivée d'un manifeste Bagages passe automatiquement les bagages actifs au statut Arrivé.
- Les bagages arrivés peuvent lancer le contrôle de retrait depuis le manifeste.

Version Android : 4.6.0 — versionCode 460.
