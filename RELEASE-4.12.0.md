# YAM TRANS 4.12.0 — applications et exploitation

## Livrables

| Application | Version | Utilisation |
|---|---|---|
| Personnel Android | 4.12.0, code 4120 | Mise à jour de YAM TRANS Test, sans désinstallation |
| Personnel Windows x64 | 4.12.0 | Installateur ou version portable ; mêmes écrans et règles métier |
| Voyageurs Android | 1.0.0, code 100 | Application distincte du personnel |
| Voyageurs web | 1.0.0 | `/voyageurs/`, interface mobile et ordinateur, manifeste et cache de l’interface |

Les APK de test sont signés avec la clé de test conservée pour les mises à jour. Le personnel garde l’identifiant `com.abzora.transfertpos.test`. Voyageurs utilise `com.yamtrans.voyageurs.test`, installable à côté. Les actifs web ont été intégrés à l’enveloppe Capacitor existante ; le code natif n’a pas été recompilé. Les installateurs Windows ne portent pas de certificat commercial.

## Corrections du guichet

- Résolution commune des arrêts : espaces, espaces insécables, casse et accents ; noms canoniques conservés dans les ventes et blocages.
- Arrêts intermédiaires acceptés sous forme de liste ou séparés par virgule, point-virgule et retour à la ligne.
- Nouveau calcul des listes d’arrêts quand un départ est actualisé. Le blocage du siège utilise le départ après synchronisation.
- Arrêt réellement absent, sens inversé et boucle ambiguë restent refusés ; les anciens enregistrements incohérents occupent leur siège par précaution.
- Les dates effacées dans le filtre des billets ne rétablissent plus silencieusement le jour courant.
- Embarquement de nuit : la fenêtre de quatre heures autour du départ complète la règle habituelle du même jour, y compris de part et d’autre de minuit.
- Tarifs de tronçon invalides refusés, compteur de charge harmonisé avec les mêmes noms d’arrêts.

Les fonctions précédentes restent présentes : photo dans l’application, OCR CNIB/passeport, QR et pièce dans la même caméra d’embarquement, naissance, conflits conservés par saisie, verrou des bordereaux arrivés, rôles et actions détaillées, affectations, paie et alertes GPS.

## Application voyageurs

Recherche des départs et tarifs ; plan des sièges ; compte personnel ; création d’une commande ; blocage du siège pendant quinze minutes au maximum ; ouverture du paiement YengaPay ; vérification du paiement ; émission atomique du billet ; QR d’embarquement ; enregistrement ou partage d’une image du billet ; historique personnel ; contact de la compagnie et aide au voyage.

Les tarifs viennent du serveur. L’application ne peut pas déclarer elle-même un paiement réussi. La vérification exige le bon identifiant YengaPay, la référence de commande, le montant exact et une devise compatible XOF. Un retour navigateur ne valide aucun paiement.

Une réponse perdue ne déclenche pas un deuxième paiement pour la même commande. Un paiement tardif ne reprend pas un siège déjà vendu. Le client voit alors « Paiement reçu · assistance requise ». Dans les rapports Tickets, le personnel habilité consulte les commandes et peut vérifier YengaPay.

Les comptes voyageurs et leurs sessions sont isolés des comptes du personnel et exclus de la synchronisation et de l’export métier. Les réservations d’autres comptes ne sont pas accessibles par numéro de téléphone.

## Activation YengaPay

Sur le projet VPS YAM TRANS uniquement, renseigner les variables dans `/opt/yamtrans-sync/.env` :

```
YENGAPAY_API_KEY
YENGAPAY_GROUP_ID
YENGAPAY_PROJECT_ID
YENGAPAY_BASE_URL
PASSENGER_COMPANY_CODE
```

`YENGAPAY_BASE_URL` vaut `https://api.sandbox.yengapay.com/api/v1` pour les essais ou `https://api.yengapay.com/api/v1` en production. `PASSENGER_COMPANY_CODE` doit désigner la société qui vend les billets, par défaut `YAMTRANS`.

Utiliser un projet marchand attribué à YAM TRANS. Ne pas réutiliser automatiquement les identifiants de Print Station. Les clés restent sur le serveur. Après modification de `.env`, recréer uniquement le conteneur API pour prendre en compte les variables. Sans configuration complète, l’achat reste désactivé et les horaires restent consultables.

La confirmation s’effectue avec « Vérifier le paiement » dans Mes billets, ou par le personnel dans Rapports Tickets. Aucun webhook n’est nécessaire à ce parcours. Les remboursements YengaPay et les litiges doivent être traités par la compagnie auprès du prestataire ; aucun remboursement bancaire ou Mobile Money automatique n’est intégré dans cette version.

## Mise à jour du VPS multi-projets

Le script serveur `update-4.12.0.sh COMMIT_SERVEUR` cible exclusivement `/opt/yamtrans-sync` et le projet Docker `yamtrans-sync`. Il vérifie l’état du dépôt, sauvegarde la base PostgreSQL et les fichiers de configuration, conserve une image de retour arrière, reconstruit et redémarre uniquement l’API. Il vérifie ensuite la version HTTPS et rétablit l’API précédente si la vérification échoue. Il ne supprime aucun volume et ne réinitialise pas la base.

Ne pas désinstaller l’APK du personnel avant sa mise à jour : les saisies locales en attente doivent être conservées. Synchroniser puis examiner les saisies à vérifier. Installer la version Windows dans le compte Windows habituel ; les données locales se trouvent dans `%APPDATA%/YamTrans`.

## Contrôles et limites pratiques

Les tests automatiques couvrent les conflits, segments, sièges concurrents, droits, documents, arrivée des bordereaux, paie, GPS, commandes voyageurs et paiements simulés. Les parcours navigateur et Electron utilisent une API locale réelle. La caméra reçoit une vidéo de test et la réponse OCR est contrôlée ; le fournisseur de paiement est simulé. Les tests ne débitent aucun compte.

Avant utilisation réelle : vérifier l’installation sur les téléphones de l’équipe et sur Windows, la permission caméra, une pièce réelle lisible, une imprimante réelle, la synchronisation avec le VPS puis une transaction YengaPay sandbox. Vérifier ensuite le projet marchand et réaliser un essai de production suivi avant d’ouvrir les ventes au public. Aucun essai physique Android, d’imprimante Windows ni débit YengaPay réel n’a été effectué dans cet environnement.

Le GPS Windows dépend du matériel et des autorisations de l’ordinateur. Pour les futurs boîtiers, choisir un modèle dont le protocole est compatible avec l’API HTTPS JSON de YAM TRANS, ou prévoir une passerelle adaptée. Un boîtier TCP/SMS ne se configure pas simplement en lui donnant l’URL HTTPS. Le suivi client n’affiche pas de fausses positions tant que les boîtiers ne sont pas installés et activés.

## Prochaines évolutions voyageurs

| Priorité | Fonction | Condition opérationnelle |
|---|---|---|
| 1 | Confirmation automatique en arrière-plan et notifications de départ | Service de notifications et retours prestataire configurés |
| 1 | Modification de voyage et remboursement en libre-service | Conditions commerciales et circuit de validation définis |
| 2 | Géolocalisation du bus et heure d’arrivée estimée | Boîtiers installés, données fiables et partage autorisé |
| 2 | Carnet de fidélité, favoris et offres anniversaire | Profil client rapproché avec consentement |
| 2 | Suivi des bagages et colis dans le compte | Preuve de propriété des envois et liens de suivi sécurisés |
| 3 | Comptes famille et réservations de groupe | Règles enfants, accompagnement et paiement groupé validés |

Ces évolutions ne sont pas présentées comme déjà opérationnelles dans l’application livrée.
