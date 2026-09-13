# Yam-Trans — corrections intégrées (v2.0 / backend 2.1)

## Fonctionnel
- Flux de statut contrôlé : Enregistré → En attente de départ → Expédié → Arrivé → Disponible → Livré.
- Le statut `Livré` ne peut plus être posé manuellement : il est attribué par le workflow de retrait.
- Création d'un bordereau = affectation au départ, et non expédition immédiate.
- Ajout de `Confirmer départ` sur les bordereaux ; cette action passe les envois concernés à `Expédié`.
- Validation d'un bordereau : tous les envois doivent avoir la même origine et la destination choisie.
- Codes bordereau renforcés avec date + séquence locale.
- Retrait bloqué tant que le solde n'est pas intégralement encaissé.
- Encaissement du solde au retrait ajouté au journal `payments`.
- Historique `events` ajouté sur les envois pour tracer les changements logistiques.
- Téléphones normalisés (espaces/tirets supprimés, prise en charge +226/+225 courante).
- Clients existants sans ID migrés automatiquement vers un UUID.
- Montant encaissé supérieur aux frais désormais refusé.

## Sécurité
- Mots de passe des nouveaux comptes stockés avec PBKDF2/SHA-256 + sel (120 000 itérations).
- Anciennes données de mot de passe en clair migrées vers un hash lors de la prochaine connexion.
- Les utilisateurs et mots de passe ne sont plus synchronisés vers le serveur.
- La session locale ne conserve plus le hash/mot de passe dans `currentUser`.
- QR d'étiquette : suppression du nom/téléphone en clair ; utilisation d'un token technique.
- Android : sauvegarde système des données de l'application désactivée (`allowBackup=false`).
- Tracking public : nom destinataire masqué ; aucun téléphone, montant ou document d'identité exposé.
- Backend : possibilité de définir une clé de synchronisation différente par agence via `SYNC_AGENCY_KEYS`.
- Backend : filtrage des données synchronisées par périmètre d'agence.
- Backend : utilisateurs retirés des types synchronisables.

## Synchronisation / backend
- Ajout de `payments` à la synchronisation.
- Détection serveur des collisions de code colis ; le serveur renvoie `conflicts` au client.
- Index dédié `shipment_index` pour accélérer le tracking public sans scanner tous les envois.
- Compatibilité conservée avec les anciennes bases : fallback sur `sync_entities`.
- CORS configurable via `CORS_ORIGINS`.
- Endpoint `/health` enrichi avec la version serveur.

## Impression
- Correction Windows : `listPairedBluetoothPrinters()` renvoie désormais la même structure qu'Android (`{devices:[...]}`).
- Le client accepte aussi bien un tableau direct que `{devices:[...]}` pour compatibilité.
- `allowReprint` réellement appliqué au reçu, à l'étiquette et à l'impression combinée.
- `receiptCopies` et `labelCopies` réellement appliqués pour l'impression native.
- Compteurs d'impression ajoutés par envoi.
- Android : correction de l'indicateur `connectionReused` du cache Bluetooth.
- Vocabulaire d'impression harmonisé vers « étiquette colis ».

## UX / vocabulaire
- « Courriers / colis » remplacé par « Envois » dans la navigation.
- « Bordereau courrier » remplacé par « Bordereau d'expédition ».
- « Bénéficiaire » harmonisé vers « Destinataire » dans les principaux parcours.
- Indicateur réseau renommé « Réseau disponible / Hors connexion » pour éviter de faire croire que le serveur est forcément joignable.
- Message de conflit de synchronisation ajouté.

## Dépendances / versions
- Dépendances npm figées sur les versions présentes dans les lockfiles au lieu de `latest`.
- Android : `versionName 2.0.0`, `versionCode 20`.
- Windows : package `2.0.0`.
- Backend : API `2.1.0`.

## Tests réalisés
- `node --check` sur les deux `main.js` et Electron.
- `python -m py_compile` sur le backend.
- Smoke test FastAPI : `/health`, synchronisation, tracking public et collision de code.
- Le build npm complet n'a pas pu être terminé dans l'environnement d'analyse (installation des dépendances trop lente), donc il faut lancer `npm ci && npm run build` sur la machine de build avant livraison finale APK/EXE.

## Points structurels non transformés dans cette passe
- Le stockage métier reste basé sur `localStorage`; migration SQLite recommandée pour la prochaine version.
- Les photos restent actuellement embarquées en Base64 dans les données locales; stockage fichier/S3/MinIO recommandé.
- La synchronisation reste une réplication complète ; une delta-sync par révision serveur reste recommandée pour très gros volumes.
- L'authentification serveur par utilisateur/JWT n'a pas été introduite afin de ne pas casser l'exploitation existante ; les clés par agence constituent une amélioration intermédiaire.
