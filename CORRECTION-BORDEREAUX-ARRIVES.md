# Bordereaux Courrier — verrouillage après arrivée

La présence de arrivedAt rend le bordereau non modifiable. Le bouton Modifier reste visible, grisé et désactivé ; Ouvrir et PDF restent disponibles. La réception d’une confirmation par synchronisation verrouille aussi les boutons et un formulaire déjà ouvert, sans attendre de changer de page. Les entrées directes et la validation du formulaire revérifient l’état courant.

Le serveur refuse les modifications du bordereau scellé, y compris l’effacement de la confirmation, la suppression ou une ancienne modification hors connexion. Les synchronisations identiques restent sans effet. Le rattachement à un autre voyage et l’ajout/retrait d’un colis du bordereau scellé sont refusés. Les étapes normales de retrait/livraison des colis restent possibles. Le rattachement déjà présent à un voyage peut être relu sans nouvelle écriture.

Validation : 134 tests serveur et 37 tests JavaScript passent ; build web réussi. Quatre nouveaux tests d’interface exécutent notamment le vrai rendu des bordereaux et le formulaire déjà ouvert. Douze cas serveur couvrent le verrou, les synchronisations, le rattachement et la poursuite du traitement des colis.

Le correctif est préparé dans les deux dépôts, avec les ressources web Android actualisées. Aucun déploiement VPS ni nouvel APK distribué pour ce correctif : ils seront réalisés dans l’étape de mise à jour.
