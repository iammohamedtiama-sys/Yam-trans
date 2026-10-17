# YamTrans 4.8.0 — exploitation et version Windows

Cette version étend les projets existants sans remplacer les modules Courrier, Bagages ou Tickets. Le même client JavaScript est utilisé sur le Web, Android et Windows. Les nouveaux écrans se trouvent dans **Tickets → Pilotage & services**.

## Fonctions livrées

| Domaine | Fonctionnement |
|---|---|
| Courrier et caisse | Les reprises d’une même opération retrouvent l’original. Les identifiants rejetés restent mémorisés par le serveur ; les paiements associés à un envoi rejeté ne deviennent pas de nouvelles recettes, même dans une synchronisation ultérieure. |
| Billetterie | Formulaire unique, bouton « Créer et imprimer », départ repris automatiquement sur les trajets directs, siège sélectionné rouge. Réservations, groupes et aller-retour de la 4.7 restent disponibles. |
| Émission interrompue | Référence d’émission conservée sur l’appareil. Après une réponse réseau perdue, « Vérifier l’émission interrompue » retrouve le billet serveur sans le réémettre. |
| Tarifs | Tarifs de ligne adulte/enfant, Simple/VIP. Tarif affiché en lecture seule au guichet ; contrôle du prix côté serveur pour les lignes configurées. Remises réservées au responsable. Les anciennes lignes sans grille conservent leur fonctionnement ; configurez leur grille pour appliquer le contrôle central. |
| Assistance | Besoin de mobilité ou de vision renseigné séparément de la catégorie tarifaire et de la classe du siège. |
| Équipage | Chauffeur et convoyeur choisis parmi les comptes actifs autorisés. Affectation vérifiée par le serveur ; modification et désactivation des comptes existantes conservées. |
| Planning et charge | Nombre de voyages sur sept jours, alertes sur le repos calculé à partir des arrivées réellement renseignées. Seuils réglables par un responsable. Ces indicateurs ne mesurent pas la fatigue. |
| Information voyageurs | Tableau des départs du jour, destinations, bus et statuts réels ; mode plein écran pour téléviseur. Pas d’heure d’arrivée obligatoire à la création du voyage. |
| GPS | Transmission ponctuelle ou suivi avec l’application ouverte, depuis le téléphone/ordinateur autorisé. Position horodatée et précision ; signalement des positions anciennes. Aucun déplacement n’est simulé. |
| Étapes et incidents | L’équipage affecté publie départ, approche, entrée en gare, arrivée et incidents. L’exploitation peut publier et révoquer un lien de suivi partageable, sans liste de passagers ni pièce d’identité. |
| Consignation | Dépôt d’une moto ou voiture à la gare, état à l’entrée, tarif journalier ou forfait, restitution, état à la sortie et encaissement calculé par le serveur. Le véhicule n’est pas transporté. |
| Flotte | Carburant, entretien, pièces et références de documents, quantité/litres, kilométrage, échéances. Une dépense est créée une seule fois ; le rattachement à un départ alimente son résultat. |
| Carnets | Vente de dix voyages ou d’un autre quota, ligne/classe, montant encaissé, date d’expiration, solde. Débit atomique d’un voyage lors de la vente d’un billet, y compris avec deux guichets concurrents. |
| Annulation prépayée | Aucun second remboursement monétaire ; le voyage non utilisé est restitué au carnet une seule fois. |
| Identité client | CNIB, passeport ou autre pièce, identifiant client stable, renouvellement et expiration. Photos conservées dans le dossier privé ; consultations tracées. Aucun préfixe de numéro n’est imposé. |
| OCR | Lecture locale par Tesseract sur le serveur, propositions de numéros et texte à vérifier. Le nom et le numéro restent confirmés par l’agent. Recherche par pièce à l’embarquement et récupération des billets du client. |
| Transfert | Un responsable peut changer le départ et le siège d’un billet non embarqué en conservant trajet et classe. L’ancien siège est libéré, les paiements sont conservés et le mouvement reste dans l’historique. |
| Analyse | Filtres de période et d’agent, résultat par départ, pic de remplissage, récapitulatif par agent, détail du départ et export CSV. Les encaissements de carnets et leur consommation sont distingués. |
| Assistant IA | Sur demande, interprétation d’un rapport agrégé sans noms, téléphones, pièces ou GPS. Aucune décision automatique. Fournisseur, clé et modèle requis ; en leur absence, le rapport chiffré reste utilisable et l’indisponibilité de l’IA est explicite. |

## Mise en service

1. Sauvegarder la base existante et déployer le serveur 4.8 avec son frontend. Les données ajoutées utilisent le stockage multi-sociétés existant, sans suppression des anciennes tables.
2. Définir `PUBLIC_BASE_URL` avec le domaine HTTPS réellement utilisé : les liens de suivi doivent être accessibles aux voyageurs.
3. Le Dockerfile installe Tesseract et sa langue anglaise. Pour une installation Python directe : installer `requirements.txt`, `tesseract-ocr` et `tesseract-ocr-eng`.
4. Renseigner les quatre tarifs des lignes, créer ou modifier les comptes d’équipage et attribuer les rôles appropriés.
5. Pour l’IA, définir uniquement sur le serveur `YAMTRANS_AI_API_KEY`, `YAMTRANS_AI_MODEL` et, si nécessaire, `YAMTRANS_AI_ENDPOINT` (endpoint HTTPS compatible Chat Completions ; OpenAI par défaut). Aucune clé n’est intégrée à l’exécutable.
6. Installer Windows x64, puis connecter le compte société. Le serveur par défaut reste `https://sync.print-station.tech` ; les nouvelles API nécessitent son déploiement en 4.8.

## Vérification et limites

Les tests couvrent les écritures concurrentes, reprises, grilles tarifaires, soldes de carnets, fonds encaissés, transferts, consignation, accès à l’identité, OCR et anonymisation de l’analyse IA. L’essai Electron sous Linux utilise une base temporaire et une impression simulée ; il vérifie la vente réelle et la reprise après perte de réponse serveur. Il ne constitue pas un test sur un PC Windows ou une imprimante physique.

Les installateurs Windows sont non signés. Le GPS dépend du matériel, des autorisations du système et du maintien de l’application ouverte. Le suivi n’est pas un service de localisation en arrière-plan Android. Les SMS et WhatsApp existants restent conditionnés à leurs fournisseurs ; l’envoi automatique à chaque étape, l’achat de billets par portail public, les paiements PSP, la comptabilité réglementaire complète, la gestion de stock de pièces et des intégrations partenaires OAuth2 ne sont pas ajoutés par cette version. L’expression « ticket deux numéros » reste à préciser avant toute modification de la numérotation.

La mise à jour du code et la génération Windows ne déploient pas automatiquement le serveur en production. Un essai sur PC Windows avec les imprimantes utilisées reste nécessaire avant exploitation en gare.

## Références publiques de périmètre

Les présentations de l’éditeur ont servi à comparer les domaines fonctionnels ; aucun code ni habillage propriétaire WicTrans n’est intégré :

- https://www.wictrans.com/
- https://www.wicsoft.africa/
- https://play.google.com/store/apps/details?id=com.wicsoft.wictransapp&hl=fr
