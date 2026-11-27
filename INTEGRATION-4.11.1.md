# YAM TRANS 4.11.1 — synchronisation et naissance

Une synchronisation concurrente ne bloque plus tous les sièges. Les versions locales refusées sont conservées, avant toute réconciliation, dans un dossier local propre à la société et au compte. Le bouton « Saisies à vérifier » permet de comparer les versions, exporter la saisie puis l’archiver ; les archives restent consultables. Si l’espace local est insuffisant pour conserver la copie, la réconciliation s’arrête. Une saisie sans version serveur est retirée des opérations validées mais reste récupérable dans ce dossier. Elle ne doit pas être considérée comme encaissée ou émise sur le serveur.

Les nouvelles ventes, blocages de sièges et règlements passent toujours par les validations serveur. Les refus de place, les protections de paiement et les permissions restent actifs. Les demandes simultanées de synchronisation partagent la même requête. Les anciennes modifications déjà écrasées par une version antérieure ne peuvent pas être reconstituées.

La date de naissance remplace l’expiration dans la vente et l’identité client. La lecture propose une naissance imprimée ou présente dans une zone MRZ de passeport ; l’agent doit la confirmer. Les dates futures et impossibles sont refusées. Les expirations historiques restent distinctes et conservent leurs contrôles de validité. Les dossiers clients enregistrent la naissance ; les billets publics n’en reçoivent pas une copie.

Clients affiche les anniversaires du jour. Conseils IA & alertes affiche un rappel agrégé, sans noms ni dates de naissance transmis à la synthèse IA. Aucun SMS automatique d’anniversaire n’est activé dans cette version ; le canal fournisseur, le modèle de message et la programmation doivent être configurés séparément.

L’en-tête mobile sépare le titre des boutons, permet le retour à la ligne et respecte l’inset supérieur déclaré par l’appareil. Un essai sur les téléphones concernés reste nécessaire.

Validation : 122 tests serveur ; 35 tests JavaScript ; parcours DOM/API des services existants ; navigateur sur 320, 360, 390, 430, 768 et 1280 px. Le parcours reproduit un conflit réel entre deux guichets, vérifie sa conservation, puis réalise une vente et un embarquement. Il vérifie aussi le préremplissage de la naissance et l’absence de chevauchement entre titre et commandes.

L’APK de test 4.11.1, code 4111, conserve l’identifiant com.abzora.transfertpos.test et la signature du test 4.11.0. Cette mise à jour remplace les ressources web de l’APK précédent et ses numéros de version ; le code natif, les bibliothèques et les ressources Android restent identiques. L’alignement, les signatures v2/v3, les versions et l’égalité des ressources web avec le build sont vérifiés. Il ne s’agit pas d’une nouvelle compilation du code Java.

Les changements sont publiés sur la branche codex/yamtrans-services-4-9. Le déploiement Hostinger et l’installation sur les téléphones ne sont pas effectués par la publication du code. Le script update-4.11.1.sh du dépôt serveur cible uniquement /opt/yamtrans-sync, sauvegarde la base et la configuration et met à jour l’API ; son exécution sur le VPS reste à faire.
