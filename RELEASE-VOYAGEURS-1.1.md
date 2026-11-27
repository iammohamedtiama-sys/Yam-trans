# YAM TRANS Voyageurs 1.1.0

Cette version remplace l’application voyageurs 1.0.0. Son APK de test garde le même identifiant Android et la même signature : installer la mise à jour sans désinstaller l’application.

## Une application pensée pour le voyageur

| Espace | Fonctions disponibles |
|---|---|
| Accueil | Identité YAM TRANS, accès aux billets et aux services, recherches récentes et lignes réellement publiées par la compagnie |
| Réservation | Recherche par villes, date et catégorie adulte/enfant, dates rapides, tri par prix ou départ, filtre Simple/VIP et choix du siège |
| Voyageur | Réutilisation d’un voyageur enregistré, informations modifiables avant confirmation et tarif vérifié par le serveur |
| Paiement | Commande idempotente, lien YengaPay, contrôle du paiement et actualisation automatique lorsque la commande est ouverte |
| Mes voyages | À venir, passés, tous, billets enregistrés, détail du voyage, statut réel, QR d’embarquement et référence |
| Billet | Enregistrement local hors connexion, PDF avec caractères français, partage quand le téléphone le permet et événement calendrier |
| Compte | Connexion persistante au choix, modification du nom et du téléphone, changement du mot de passe et déconnexion avec suppression des billets locaux |
| Mes voyageurs | Ajout, modification et retrait ; nom, téléphone et naissance facultative ; douze voyageurs maximum |
| Favoris | Ajout et retrait des trajets, synchronisation avec le compte et relance d’une recherche |
| Services | Agences publiées, adresses, appel, itinéraire et suivi d’un colis par sa référence sans exposer les noms ni téléphones de tiers |
| Mes demandes | Assistance, bagages, modification, annulation/remboursement, suivi du traitement et réponse écrite de la compagnie |
| Suivre mon car | Lien affiché dans le billet uniquement si la compagnie a activé un partage pour ce voyage ; aucune position fictive |

Le personnel traite les demandes dans **Rapports Tickets → Demandes des voyageurs** sur l’interface web mise à jour. L’envoi d’une demande ne modifie ni le billet ni les montants encaissés. Un remboursement ou un changement de départ doit être validé et exécuté par la compagnie.

## Design et confort d’utilisation

Interface adaptée au téléphone et à l’ordinateur, navigation mobile en cinq espaces, menu latéral sur ordinateur, police Manrope embarquée et sous licence OFL, pictogrammes cohérents, étapes de réservation, plan des sièges, billet avec QR, formulaires lisibles et états de chargement et d’erreur. Le plan reprend les positions de sièges lorsqu’elles sont renseignées dans la configuration du véhicule. Les listes sans positions restent présentées avec leurs numéros réels.

Les données personnelles sont liées au compte. La sortie du compte efface les billets téléchargés dans l’espace local de l’application ; un PDF déjà exporté reste sous le contrôle de son propriétaire. Une actualisation en ligne met aussi à jour les billets précédemment conservés hors connexion. La version hors connexion affiche la dernière information enregistrée, qui peut évoluer côté compagnie.

## Serveur nécessaire : 4.13.0

La version 1.0.0 avait été livrée avant la mise en ligne de son API. Le contrôle public du 27 novembre 2026 a confirmé un HTTP 404 sur `/api/v2/passenger/config`. La nouvelle version ne présente plus ce défaut comme une liste de départs vide : elle indique clairement l’indisponibilité et propose de réessayer.

Déployer le serveur 4.13.0 dans le projet **`/opt/yamtrans-sync`** avec le script **`update-4.13.0.sh`**. Ce script vérifie le projet Docker `yamtrans-sync`, sauvegarde PostgreSQL et les fichiers de configuration, conserve l’image précédente et ne remplace que le service API. Il vérifie ensuite la version HTTPS ; son retour arrière conserve les volumes et les données.

Le code société public vient de `PASSENGER_COMPANY_CODE`, par défaut `YAMTRANS`. Il doit désigner la compagnie active qui exploite les services. Les agences, départs, véhicules, classes, arrêts et tarifs proviennent de son paramétrage réel. Les comptes et services restent accessibles si la billetterie n’est pas activée ; la création d’une nouvelle vente reste alors interdite.

Pour le paiement réel, renseigner sur ce même projet :

- `YENGAPAY_API_KEY` ;
- `YENGAPAY_GROUP_ID` ;
- `YENGAPAY_PROJECT_ID` ;
- `YENGAPAY_BASE_URL`, production ou sandbox.

Ces identifiants restent sur le serveur et ne sont pas inclus dans l’APK. Un projet marchand attribué à YAM TRANS doit être choisi. L’absence de configuration désactive l’achat ; elle ne produit pas de faux paiements ni de billets fictifs. Aucun remboursement Mobile Money automatique n’est intégré.

## Validation réalisée

- 163 tests serveur : sièges et conflits, droits, comptes, commandes, montants et références du prestataire, sessions, voyageurs, favoris, demandes et réponses, données publiques des colis et partage GPS activé/révoqué.
- 43 tests JavaScript de non-régression du personnel.
- Parcours voyageurs avec API locale réelle et prestataire de paiement simulé : compte, voyageur enregistré, favori, réservation, confirmation, PDF, calendrier, QR après rechargement complet sans Internet, demande de modification, réponse depuis l’interface du personnel, profil et déconnexion.
- Contrôle de l’affichage de 320 à 1 366 pixels et inspection visuelle de l’accueil, des départs, des sièges, du billet et des demandes. Le PDF a été rendu et son texte vérifié, y compris les accents.
- APK version 1.1.0, code 110, signature de test compatible avec la version 1.0.0. Enveloppe Capacitor existante conservée ; bytecode natif inchangé.

Les essais avec un appareil Android physique et une transaction YengaPay réelle restent à réaliser. Cette livraison ne revendique pas une mise à jour effective du VPS tant que l’exécution du script et les contrôles publics n’ont pas été observés.
