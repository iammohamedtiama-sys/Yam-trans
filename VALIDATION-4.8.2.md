# Validation Android 4.8.2

## Corrections vérifiées dans le code et les tests

- Deux actions Android distinctes : prise de vue via l’application caméra avec permission explicite, et import via le sélecteur de documents Android. Le fichier temporaire caméra est privé, puis supprimé après traitement ou annulation.
- OCR ML Kit latin embarqué, avec rotation EXIF et réduction d’image. Modèles et bibliothèques OCR vérifiés dans l’APK. Vente, embarquement et Identité client utilisent ce lecteur Android.
- Propositions de numéro et de nom à partir du texte OCR ; numéro prérempli, confirmation humaine obligatoire. Les tests de parsing ne mesurent pas l’exactitude de reconnaissance sur des CNIB réelles.
- Tarif affiché par un output, aucun champ tarif visible ; remise supprimée. Prix recalculé à l’envoi. Le serveur refuse les prix divergents et les nouvelles ventes remisées, y compris par synchronisation.
- Point d’embarquement fixé au départ de la ligne ; sélection de descente conservée pour les escales.
- Jeton de connexion hors ligne conservé avec le compte auquel il appartient. Une ancienne session plateforme n’ouvre pas de retour administrateur pour un compte agence. Les réponses de synchronisation d’une ancienne session sont ignorées.

## Résultats

- **63 tests serveur réussis**.
- **14 tests JavaScript réussis** : règles transport/impression, extraction de texte et association compte/jeton.
- **Parcours d’interface Electron réussi** : vente enfant avec photo synthétique et réponse OCR contrôlée, préremplissage du numéro, contrôle du champ tarif caché modifié, embarquement, reprise après réponse perdue, modification de compte, pilotage, puis navigation d’un compte agence et connexion hors ligne avec un ancien jeton administrateur volontairement laissé sur l’appareil.
- Construction Vite du client et du frontend serveur réussie.
- `assembleDebug` Android réussi avec Java 21 et SDK 36. Version 4.8.2 / code 482 ; Android 7 et supérieur.
- Tous les fichiers web embarqués comparés octet par octet au build final. Contrôle CRC du ZIP APK réussi.
- Signature APK vérifiée et identique à la livraison 4.8.1 : empreinte du certificat `7e77058c56e8ea0b740264b1a59fa453eae48bb7d967264c7937c3476e46fd97`.
- SHA-256 du fichier APK : `d91732f8a2c588bdeb755248cfa8ef9b741c177bb320ecb1977bea3033338297`.

## Recette restant sur téléphone

Aucun téléphone Android ni caméra physique n’était connecté à cet environnement. L’ouverture effective de la caméra sur le modèle du client, la reconnaissance d’une vraie CNIB (netteté, reflets, orientation), le cycle d’annulation/refus de permission et l’impression physique restent à vérifier sur appareil. Le test d’interface utilise Electron sous Linux ; sa réponse OCR est contrôlée pour vérifier le parcours et ne prouve pas la reconnaissance d’un document réel.

L’APK reste signé avec une clé de développement. Sa signature correspond à l’APK 4.8.1 livré ; la signature d’une ancienne version antérieure non fournie n’est pas connue. Ne pas désinstaller une ancienne application sans préserver les opérations non synchronisées.

L’OCR Android fonctionne localement ; l’enregistrement de la pièce et du billet, ainsi que l’embarquement commun aux agences, exigent le serveur mis à jour. Aucun déploiement de production n’est effectué par un simple push Git.

## Reproduire la compilation

Exécuter `npm ci`, puis `npm run android:debug` avec Java 21 et le SDK Android installé. Cette commande construit le client, synchronise Capacitor puis lance Gradle afin de ne pas réutiliser un ancien écran Android. Pour réutiliser la signature de développement conservée séparément, renseigner `YAMTRANS_DEBUG_KEYSTORE` avec son chemin local. Ne jamais ajouter la clé à Git.
