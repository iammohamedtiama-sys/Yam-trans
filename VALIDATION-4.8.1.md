# Validation YamTrans 4.8.1

- Serveur : 61 tests API/unitaires réussis, dont 7 nouveaux tests couvrant photo + vente atomique, refus des pièces invalides/expirées, recherche, embarquement, autorisations, rollback et modification/désactivation des comptes.
- Application : 9 tests de règles métier et d’impression réussis.
- Interface Electron : parcours complet réussi avec photo synthétique et réponse OCR contrôlée ; vente réelle via API, recherche par CNIB, embarquement serveur, modification nom/mot de passe/rôles d’un compte et connexion avec le nouveau mot de passe. Le scénario vérifie aussi la reprise après réponse de vente perdue, les tarifs enfant, le siège rouge, le parking et les écrans de pilotage. Aucune exception JavaScript observée.
- Frontend serveur : construction Vite réussie après installation depuis le lockfile.
- Android : `assembleDebug` réussi avec Java 21, SDK 36, versionName 4.8.1 et versionCode 481, applicationId conservé `com.abzora.transfertpos`.
- APK : signature APK v2 vérifiée ; tous les fichiers web embarqués comparés octet par octet au build final.
- SHA-256 APK : `de9f1907d46482a033edcf2334417df2c06470104fe98d6faf5d67399b470dab`.

L’APK utilise une signature de développement. L’ancienne clé de signature n’a pas été fournie ; une mise à jour par-dessus une ancienne installation n’est pas garantie. La clé de développement de cette livraison est conservée séparément et n’est jamais versionnée dans Git.

Les tests d’interface exécutent le client avec Electron sous Linux. Caméra Android, lecture d’une vraie CNIB, imprimante, installation sur téléphone et GPS physique restent à tester sur appareil. L’OCR réel dépend de Tesseract installé sur le serveur ; la reconnaissance n’est pas simulée dans l’application livrée.

Le contrôle en ligne du 17 octobre 2026 à 21:54 UTC a retourné le serveur 4.6.3. Le serveur 4.8.1 doit être déployé pour les nouveaux parcours. Aucun déploiement de production n’a été exécuté pendant cette correction.
