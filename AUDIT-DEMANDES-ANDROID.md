# YamTrans — reprise des demandes Android

## Correction 4.8.1

L’Android du dépôt était resté déclaré en version 4.7.0. La livraison des exécutables Windows n’avait pas produit un nouvel APK. En 4.8.0, la gestion des pièces était séparée de la vente et de l’écran d’embarquement.

La correction 4.8.1 réunit ces parcours :

1. **Vente** : photographie CNIB/passeport, lecture OCR proposant des numéros, vérification manuelle du numéro et du nom, expiration, paiement et siège. La pièce et le billet sont enregistrés dans la même transaction. La photo est privée et n’entre ni dans le billet public ni dans la synchronisation générale.
2. **Embarquement par pièce** : choix obligatoire du départ, photographie ou saisie du numéro, recherche du billet, comparaison à la photo enregistrée, puis validation serveur. Mauvais départ, mauvais jour, pièce expirée et solde impayé sont refusés. Une seconde validation retrouve le même embarquement.
3. **Comptes** : bouton Modifier dans la liste des utilisateurs ; nom, identifiant, agence, rôle, modules, rôles billetterie, nouveau mot de passe et état actif. La désactivation reste réversible pour conserver l’historique des ventes. Les autorisations sont relues depuis le compte pour les sessions société déjà ouvertes.
4. **Manifeste** : numéro de pièce et points de montée/descente dans le contrôle interne des passagers.
5. **Guichet** : conservation du plan et de la sélection pendant une actualisation de la page ; récupération du profil client serveur après l’enregistrement de sa pièce.

## Vérification de l’ensemble des demandes retrouvées

« Présent dans le code » ne signifie pas « disponible dans l’ancien APK » ni « déployé sur le serveur de production ».

| Demande | État dans les sources | Limite ou point restant |
| --- | --- | --- |
| Formulaire de vente unique, bouton final Créer et imprimer | Présent | Impression physique Android à tester sur le matériel |
| Tarifs de ligne verrouillés, adulte/enfant, Simple/VIP | Présent | Tarification spécifique malvoyant distincte de l’assistance non ajoutée |
| Sièges choisis en rouge, plans de bus | Présent | Vérification sur téléphone physique restante |
| Point d’embarquement par défaut au départ, escales | Présent | Les escales restent choisissables |
| Aller-retour | Présent dans Groupe / aller-retour | Entrée séparée du formulaire individuel ; photo CNIB intégrée au guichet individuel seulement |
| Anti-doublon envois/encaissements et reprise réseau | Présent, tests API | Tous les anciens clients doivent utiliser le serveur mis à jour |
| Photo de pièce lors de la vente | Corrigé en 4.8.1 | Connexion obligatoire pour enregistrer pièce et billet ensemble |
| CNIB remplaçant le billet à l’embarquement | Corrigé en 4.8.1 | OCR propose le numéro ; l’agent confirme l’identité avant validation |
| Ancien client, expiration, renouvellement, consultation photo | Présent | Renouvellement dans Pilotage & services → Identité client |
| Alerte mauvais voyage, transfert contrôlé et siège libre | Présent | Transfert réservé au responsable ; aucun transfert automatique au scan |
| Modifier comptes, rôles et affectations | Présent, accès direct ajouté | Suppression réalisée par désactivation pour préserver l’historique |
| Comptes chauffeurs/convoyeurs, planning et statistiques | Présent | Repos calculé à partir des horaires effectivement renseignés |
| GPS partageable et incidents convoyeur | Présent | Application ouverte ; suivi Android en arrière-plan non ajouté |
| Écran départs/arrivées type gare | Présent | Pas de prédiction automatique des heures d’arrivée |
| Carnets prépayés avec nombre de voyages et expiration | Présent | Pas d’abonnement récurrent avec prélèvement automatique |
| Voyage privé / affrètement | Non couvert | Devis, réservation exclusive et facturation dédiés à développer |
| Consignation motos/voitures à la gare | Partiel | Dépôt/retrait/état/durée/tarif/recettes présents ; emplacement, grille centrale et reçu dédié à compléter |
| Bagages, bagagistes et manifestes liés au départ | Présent | Recette réelle avec les équipes en gare restante |
| Fidélité et filtres de rapports | Présent | Fidélité synchronisée avec le profil client |
| Charges, carburant, maintenance, documents véhicules | Présent | Les événements de pièces ne constituent pas un stock de magasin |
| Stock complet de pièces détachées | Non couvert | Entrées/sorties/inventaire/seuils à développer |
| Analyse et IA | Partiel | Rapport calculé présent ; IA nécessite une clé et un modèle serveur configurés |
| SMS de voyage à chaque étape | Non couvert | Les notifications existantes ne couvrent pas ce scénario complet |
| Comptabilité | Partiel | Caisse, recettes et charges ; pas de comptabilité générale réglementaire complète |
| Ensemble des fonctions WicTrans | Parité non démontrée | Ne pas présenter l’intégration comme une reproduction complète de WicTrans |
| Ticket à deux numéros | Sens non établi | Aucune règle métier inventée pour cette formulation |

## Livraison et serveur

L’APK 4.8.1 nécessite le serveur 4.8.1 pour les opérations photo + vente et embarquement contrôlé. Une mise à jour des sources Git ne déploie pas le serveur. Le dernier contrôle antérieur indiquait 4.6.3 en production.

Le binaire fourni pour recette utilise une signature de développement. La mise à jour directe d’une installation existante exige la même clé de signature ; sa compatibilité avec une ancienne APK non fournie n’est pas établie. Aucune désinstallation avec perte de données n’est nécessaire pour vérifier les sources et les tests.

Les tests d’interface utilisent Electron avec une photo synthétique, une réponse OCR contrôlée et l’API réelle pour la vente, la recherche, l’embarquement et la modification de compte. Ils ne remplacent pas un essai de caméra, OCR sur vraie CNIB, imprimante et GPS sur téléphone Android.
