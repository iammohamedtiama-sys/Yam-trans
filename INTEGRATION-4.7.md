# YamTrans 4.7.0 — intégration transport

Version de travail du 16 octobre 2026. Sources application, Android et serveur mises à jour. Aucune publication en production, aucun changement des données de production.

## Périmètre conservé

Les modules Courrier, Bagages et Tickets restent présents, avec leurs écrans, comptes, sociétés, droits, QR, impressions, photos, manifestes, clients, fidélité et synchronisation. Les nouvelles données utilisent le stockage d’entités déjà en place. Aucune table historique n’est supprimée.

Bases utilisées :

- application `iammohamedtiama-sys/app-2` : `6b04fe331209bc19c02d66b7cdf4320c07910e4c` ;
- serveur `iammohamedtiama-sys/Yam-trans` : `7d4ab51b9983804b0998e9e5d77dcd8b32d7ad6a`.

## Fonctions ajoutées ou renforcées

| Fonction | Comportement dans cette version |
|---|---|
| Vente simultanée | Contrôle serveur de l’allocation d’un siège sur un tronçon. Le même contrôle s’applique aux billets saisis hors connexion lors de leur synchronisation. |
| Blocage temporaire | Siège bloqué cinq minutes pour un utilisateur et son appareil. Le changement de siège libère le précédent. |
| Vente groupée et aller-retour | Jusqu’à dix passagers et vingt billets. Attribution de tous les sièges dans une même transaction ; aucun billet n’est créé si une place est indisponible. |
| Réservations | Expiration renseignée, acompte, conversion en billet et annulation des réservations sans acompte. Les acomptes non convertis figurent dans le contrôle de caisse du départ. |
| Annulation et remboursement | Validation par un responsable, conservation de l’encaissement initial, enregistrement séparé du remboursement, libération du siège et prise en compte des retenues dans les recettes. |
| Attente | Inscription par voyage, ordre chronologique, reprise du nom et du téléphone dans la vente, clôture manuelle après traitement. |
| Changement de bus | Contrôle des numéros et classes des sièges occupés. Mise à jour des billets sans déplacer le voyage ni détacher les bagages. |
| Départs récurrents | Reproduction d’un départ sur soixante dates au maximum. Les confirmations de départ et d’arrivée ne sont pas recopiées. |
| Contrôle intégré | Passagers embarqués, bagages non chargés, propriétaires non embarqués et limites de soute. |
| Courrier dans un voyage | Rattachement explicite d’un bordereau existant. Les colis, leur poids et leurs recettes rejoignent le contrôle du départ. |
| Dépenses et clôture | Billets, bagages, courrier, acomptes, remboursements, dépenses, espèces attendues, montant compté et écart. Relevé conservé au moment de la clôture. |
| Tarification et occupation | Le tarif de tronçon existant alimente la vente ; le pic d’occupation tient compte des passagers successifs. |
| Web et téléphone | Route dédiée `/app/tickets/exploitation`, correction du chargement direct des routes web, formulaire de vente complet sans masquage du paiement et reprise des anciennes clés locales. |

## Utilisation

Dans Tickets, ouvrir **Exploitation transport**, choisir un départ, puis actualiser le serveur. Les fonctions sont affichées selon les rôles Vente, Dispatch, Manager et Rapports.

- Le blocage et la confirmation des ventes connectées passent par le serveur.
- La saisie hors connexion reste disponible. Le billet est marqué « À synchroniser » et porte une mention de confirmation au guichet. Deux appareils déconnectés ne peuvent pas garantir ensemble une place disponible.
- Une vente hors connexion refusée par le serveur reste identifiable avec la mention « À régulariser : conflit de siège ». L’agent doit traiter le client et l’encaissement correspondant.
- Le changement de bus exige un plan compatible. Le remappage automatique vers d’autres numéros de sièges n’est pas implémenté.
- Les limites de soute produisent des alertes ; elles ne bloquent pas physiquement le départ.
- Le relevé de clôture est un instantané : il ne ferme pas les écritures futures et ne remplace pas une comptabilité réglementaire.
- Les montants sont des règlements déclarés. L’application ne déclenche pas de transfert bancaire ni de remboursement mobile money réel.

## Écart avec la demande « toutes les fonctions des six projets »

Cette livraison constitue une intégration concrète des fonctions transport décrites ci-dessus. **Elle ne reprend pas encore toutes les fonctions de tous les dépôts.**

| Fonction de référence non reprise | Situation |
|---|---|
| Assistant Gemini avec historique | Non intégré. Aucun fournisseur ni clé n’est configuré. |
| Paiement en ligne et remboursement par prestataire | La saisie des modes de paiement existe ; les transactions réelles par API ne sont pas intégrées par cette version. |
| QR signé Ed25519 et révocation cryptographique hors connexion | Le contrôle QR historique de YamTrans est conservé. Il ne devient pas une signature cryptographique. |
| Moteur de tarifs WebAssembly, import GTFS, connexions PSS | Non intégrés. |
| Portail autonome de réservation client avec inscription et récupération de compte | Les pages publiques de suivi et de billet existantes sont conservées ; un nouveau portail d’achat n’est pas ajouté. |
| Validation de remboursement à deux niveaux | Un responsable valide l’enregistrement. Il n’existe pas encore de demande puis approbation par une seconde personne. |
| Import de feuilles Excel pour toutes les entités | Non ajouté. Les exports et outils historiques sont conservés. |
| Points de fidélité des nouvelles ventes groupées | Le programme existant reste présent ; l’attribution automatique aux commandes groupées n’est pas ajoutée. |

Plusieurs annonces des dépôts ne correspondent pas à des fonctions immédiatement réutilisables. Le dépôt openjanala contient surtout un squelette et de la documentation. Lulan est explicitement en pré-1.0. Les applications Laravel et le serveur Rust ne sont pas copiés dans le serveur Python de YamTrans : les règles ont été implémentées dans son architecture existante.

## Vérifications

- 28 tests API : concurrence réelle entre cinq demandes, segments successifs, atomicité d’une commande groupée, reprise après nouvelle tentative, blocage temporaire, montants, réservations, acomptes, remboursement, rattachement Courrier, récurrence, changement de bus, clôture, droits et séparation des sociétés.
- 5 tests JavaScript : expiration, tarifs de tronçon, occupation et recettes après remboursement partiel.
- Compilation Vite application et web.
- Synchronisation Capacitor Android.
- Parcours navigateur : exploitation, liste d’attente, reprise dans la vente, blocage d’un siège, champs de paiement visibles sur téléphone, quatre billets pour deux passagers en aller-retour.
- Aucun test de charge PostgreSQL ni essai sur imprimante physique. Aucun APK signé ni installateur Windows produit.

## Mise en place depuis l’archive

L’archive contient les dossiers `app-2` et `Yam-trans`. Le dossier `correctifs` contient les différences par rapport aux bases listées plus haut.

Avant remplacement d’un service existant, conserver sa configuration, ses volumes et sa base. L’archive ne contient ni fichier `.env`, ni base de données, ni dépendances installées.

Serveur et interface web, depuis le dossier `Yam-trans` :

```bash
docker compose up -d --build
```

Application, depuis le dossier `app-2` :

```bash
npm ci
npm run build
npx cap sync android
```

L’ouverture et la signature Android se font ensuite avec la chaîne de publication habituelle. Les ressources Android synchronisées sont incluses. Le code de l’installateur Windows n’est pas présent dans les dépôts récupérés.

Les deux dépôts doivent être mis à jour ensemble : la nouvelle application utilise les nouvelles API `/api/v2/transport`. Ne pas relancer un script qui télécharge l’ancienne branche distante avant d’y avoir poussé ces changements.

Tests serveur :

```bash
python -m pip install -r requirements.txt pytest httpx
python -m pytest tests -q
```

Tests client :

```bash
node --test tests/transport-model.test.js
```

## Références téléchargées

| Dépôt | Révision examinée |
|---|---|
| [Bus-Ticketing-Management-System](https://github.com/openjanala/Bus-Ticketing-Management-System) | `bdece233a2b0e68a2ea9e148d6c58a2183da56b6` |
| [Bus-Ticketing-System](https://github.com/Web-Dev-Kombee/Bus-Ticketing-System) | `2df8cb3996f27d47559114531b187ffea9cea045` |
| [FUTABUS](https://github.com/scoppy9201/FUTABUS) | `9faf6f946efc994650f55651b72184d4aab9f196` |
| [bus-booking-system](https://github.com/lukaszwoznica/bus-booking-system) | `1d1ca2f9c32c37d6deeccba212295c68b0d9011d` |
| [lulan](https://github.com/lulan-sh/lulan) | `ede6c7ffe36531a4f4d7029b74a168311b11cf86` |
| [transport_management_system](https://github.com/sixtusagbo/transport_management_system) | `74bbaad72be8746611d64e43c3968851ec0dab66` |

Les références ont servi à la comparaison fonctionnelle. Leur code n’a pas été incorporé dans YamTrans. Les liens et révisions permettent de retrouver les sources examinées.
