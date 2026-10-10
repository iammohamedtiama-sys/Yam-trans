# YAM TRANS v4.5.0 — Analyse, manifestes, anti-doublons et PDF

## Courrier
- Un colis déjà rattaché à un bordereau est verrouillé contre l'annulation ordinaire. Seul le Super Super Admin plateforme peut annuler une opération, y compris lorsqu'elle est déjà sur un bordereau.
- Les agences peuvent définir leurs destinations autorisées. Par défaut, une agence peut envoyer vers toutes les autres agences actives de la société.
- Les analyses Courrier proposent : Afficher liste, Récapitulatif par agence, par agent, par jour et par mois.

## Bagages
- Scan QR/code disponible au chargement, à l'arrivée et au retrait.
- Les manifestes bagages peuvent être visualisés et imprimés.
- Le bouton « Confirmer arrivée » d'un manifeste marque automatiquement comme Arrivé tous les bagages actifs du voyage qui ne sont pas déjà retirés ou annulés.
- Les filtres Bagages couvrent période, agence, agent, statut, origine, destination, type et recherche.
- Les mêmes récapitulatifs analytiques que Courrier sont disponibles.

## Tickets
- Filtres renforcés : période, agence, agent, ligne, bus, destination, statut de voyage, statut billet et recherche.
- Récapitulatifs par liste, agence, agent, jour et mois.

## Anti-doublons
- Protection serveur contre les doubles créations Courrier, Ticket et Bagage provenant du même appareil dans une fenêtre courte.
- Le client v4.5 supprime de sa copie locale les opérations que le serveur a rejetées comme doublons.
- Les anciens doublons déjà enregistrés ne sont pas supprimés automatiquement afin d'éviter les faux positifs ; ils peuvent être annulés par le Super Super Admin.

## PDF / impression
- Résolution du nom réel de l'agent à la place des UUID techniques.
- Normalisation des séparateurs de milliers et des espaces insécables pour éviter les caractères erronés dans jsPDF.
- Nettoyage des caractères Unicode sensibles (flèches, tirets spéciaux, puces) dans les PDF.
- Amélioration du wrapping et de la mise en page des rapports, bordereaux, billets, reçus et étiquettes.

## Version
- Android : 4.5.0 (`versionCode 450`).
- API / Web : 4.5.0.
