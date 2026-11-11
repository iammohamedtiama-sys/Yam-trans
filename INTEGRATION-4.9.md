# YAM TRANS 4.9 — services de gare et exploitation

Cette livraison conserve les modules Courrier, Bagages, Tickets, CNIB/OCR, impression et synchronisation. Les nouveaux parcours sont accessibles dans **Tickets → Services avancés**, sur le Web, Android et Windows.

## Fonctions ajoutées

| Domaine | Fonctionnement |
|---|---|
| Recherche | Départ, arrivée et date ; disponibilités calculées sur le serveur par tronçon, classe et siège ; passage au guichet pour les départs à l’origine de la ligne. Aucun nom ni téléphone de passager n’entre dans les résultats. |
| Calendrier | Programmation selon les jours de semaine, depuis un départ modèle, sur un intervalle maximal de 90 jours. Durée estimée obligatoire, création atomique et reprise idempotente. Les équipages ne sont pas recopiés automatiquement : l’exploitation les affecte aux nouveaux départs. |
| Disponibilité des bus | Contrôle commun aux calendriers, affrètements, nouveaux départs synchronisés, répétitions et remplacements de bus. Les voyages historiques sans fin renseignée occupent une fenêtre estimée de quatre heures. Cette estimation doit être remplacée par les durées réelles pour les longues lignes. |
| Pièces détachées | Références, unité, stock minimum, entrées, sorties et historique. Une sortie exige un bus ; le stock négatif est refusé, même entre agents concurrents. L’achat produit une dépense ; l’utilisation de la pièce produit un événement flotte sans seconde dépense. Le mode de paiement des achats est conservé dans les dépenses. Les corrections passent par un mouvement compensatoire documenté ; il n’y a pas d’édition silencieuse des mouvements. |
| Voyages privés | Affrètement d’un bus, client, téléphone, trajet, créneau, prix convenu, acompte et règlements complémentaires. Relevé PDF. Une annulation avec acompte reste bloquée tant qu’un parcours de remboursement dédié n’est pas ajouté. Les encaissements privés sont présentés dans leur écran propre, sans intégration à la comptabilité générale. |
| Parking | Emplacements Moto/Voiture, tarif journalier ou forfait, occupation et reçu PDF de dépôt/restitution. Le serveur impose le tarif de l’emplacement et refuse sa double occupation. Le parcours parking existant utilise également ces emplacements. |
| Étapes du voyage | Option réservée au responsable ; chaque événement d’équipage prépare un SMS/WhatsApp par téléphone et canal activé. Les positions GPS ne produisent pas de message. L’écran traite dix messages en attente par action. Une réponse fournisseur incertaine est marquée « À vérifier » et n’est pas renvoyée automatiquement. |
| Export société | Export serveur de toutes les entités métier de la société, y compris identité, carnets, parking, stock, affrètements et historique. Mots de passe et paramètres secrets de la société exclus. L’export local historique inclut désormais les tableaux Tickets, Bagages et fidélité. |

Les créations sensibles sont liées à un identifiant et au contenu de la demande. Réutiliser la même référence avec un autre contenu est refusé. Les nouvelles entités financières et opérationnelles ne sont pas modifiables par la synchronisation générique.

## Correspondance avec les cinq projets examinés

| Référence | Apport retenu pour YAM TRANS | État |
|---|---|---|
| [Bus Booking System](https://github.com/lukaszwoznica/bus-booking-system) | Recherche par trajet/date et calendrier de départs | Recherche et calendrier ajoutés ; comptes clients publics et e-mails non intégrés. |
| [Bus Ticketing System](https://github.com/Web-Dev-Kombee/Bus-Ticketing-System) | Choix des sièges, QR, PDF et contrôle du billet | Parcours YAM TRANS existants conservés et couverts par les tests de régression. |
| [Transport Management System](https://github.com/sixtusagbo/transport_management_system) | Voyageurs, fret, chauffeurs et véhicules dans une même gestion | Modules existants conservés ; affrètement privé ajouté. Paystack non intégré. |
| [Fleetbase](https://github.com/fleetbase/fleetbase) | Exploitation de flotte, stocks, affectations et suivi | Stock, mouvements, alertes et conflits d’affectation ajoutés ; GPS existant conservé. Les modules Fleetbase, entrepôts complets, optimisation routière et application Navigator ne sont pas installés. |
| [Lulan](https://github.com/lulan-sh/lulan) | Inventaire par tronçon, réservations concurrentes et reprises idempotentes | Moteur YAM TRANS conservé ; recherche serveur et opérations idempotentes étendues. Le moteur Rust, les QR signés hors connexion et les connecteurs de paiement Lulan ne sont pas installés. |

Il s’agit d’implémentations natives dans YAM TRANS. Aucun code des cinq applications n’a été copié, aucune dépendance vers leurs moteurs n’a été ajoutée et aucune compatibilité API avec leurs services n’est revendiquée. Cela évite de mélanger les architectures PHP, Python et Rust ainsi que leurs licences différentes.

## Mise en service

1. Sauvegarder PostgreSQL et les opérations locales non synchronisées.
2. Déployer ensemble le serveur et son frontend de cette livraison, puis mettre à jour les clients. Le stockage utilise les entités existantes ; aucune suppression de table n’est requise.
3. Vérifier `/health` : version 4.9.0. Le serveur et l’application sont dans les branches `codex/yamtrans-services-4-9` de leurs dépôts respectifs.
4. Donner les droits nécessaires : exploitation pour stock/calendrier/affrètement, vente pour consignation et règlements privés, rapports pour les messages, responsable pour les tarifs parking et exports complets.
5. Créer les références de pièces puis les entrées initiales. Définir les emplacements et tarifs parking avant d’enregistrer de nouveaux dépôts avec emplacement.
6. Pour les communications, configurer les fournisseurs existants, activer les canaux de la société puis l’option Messages par étape. L’envoi est une action de l’écran ; aucun worker automatique n’est installé.

Le code seul ne met pas à jour le serveur de production. Les actifs web Android sont synchronisés avec les sources ; aucun nouvel APK ni installateur Windows n’est livré dans cette modification.

## Validation

- 82 tests serveur réussis : régressions existantes et 19 tests couvrant les nouvelles règles, les reprises, le stock concurrent, les créneaux, les permissions, les messages et l’isolation des exports.
- 14 tests JavaScript existants réussis.
- Parcours DOM/API réussi : recherche, entrée/sortie de stock, vidage des formulaires, acompte puis règlement privé, consignation, reçus PDF, CSV stock, calendrier, préférences de messages et export société. Le test utilise les vraies API Python et une base temporaire, sans réseau de production.
- Compilation Vite de l’application et du frontend serveur ; synchronisation des actifs Android.
- Le navigateur Chromium ne peut pas démarrer dans l’environnement de préparation (restriction système sur les sockets). Le test DOM/API ne valide donc pas le rendu visuel réel, les interactions tactiles ni les appareils physiques.

### Reproduire

Dans le dépôt serveur : `python -m pip install -r requirements-dev.txt`, puis `python -m pytest -q`.

Dans le dépôt application : `npm ci`, puis `npm run desktop:test` et `npm run build`.

Pour le parcours DOM/API, installer aussi les dépendances Python du serveur, définir `YAMTRANS_TEST_SERVER` avec le chemin du dépôt serveur et, si nécessaire, `YAMTRANS_TEST_PYTHON` avec son interpréteur Python, puis lancer `npm run extensions:test` depuis l’application. Le test crée sa propre base temporaire.

## Limites à conserver lors de la recette

Les paiements PSP automatiques, l’achat public en ligne, le GPS Android en arrière-plan, les QR signés et validés hors connexion, les abonnements à prélèvement récurrent, la comptabilité générale et le remboursement des affrètements ne font pas partie de cette livraison. Les tarifs spécifiques de déficience visuelle et le « ticket à deux numéros » restent à définir ; aucun prix ni règle n’a été inventé.

Les exportations métier contiennent des données personnelles et ne remplacent pas une sauvegarde PostgreSQL. Elles n’incluent pas les tombstones supprimés, les mots de passe ou la configuration secrète des fournisseurs. Leur restauration doit être préparée et contrôlée par un administrateur ; l’ancien import local refuse ce format serveur.
