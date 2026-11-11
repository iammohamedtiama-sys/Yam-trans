# YAM TRANS 4.11 — Caméra, personnel et aide à la gestion

## Caméra et billetterie

La vente commence par la photo de la CNIB ou du passeport. Le nom, le numéro B/A et la date d’expiration sont proposés lorsqu’ils sont lisibles ; les champs restent corrigeables et l’agent confirme la pièce. Le téléphone, absent de la pièce, reste à saisir. À l’embarquement, un seul lecteur intégré à l’application détecte les QR en continu et permet de photographier une CNIB ou un passeport pour retrouver le billet. Les flux caméra sont arrêtés à la fermeture et à la navigation.

Sur Android, la caméra reste dans la WebView et la reconnaissance de la photo utilise ML Kit embarqué. Dans le navigateur, l’OCR passe par Tesseract sur le serveur de la société. Ces parcours ne lancent plus l’application appareil photo externe et ne proposent pas de galerie.

## Comptes et autorisations

Dix profils : chauffeur, convoyeur, guichet, contrôleur, exploitation, caisse, comptabilité/paie, mécanicien/magasinier, responsable de gare et profil personnalisé. La matrice comprend 56 actions. Les autorisations explicites sont contrôlées côté serveur sur les opérations dédiées et sur les modifications synchronisées. Les anciens comptes gardent leurs droits hérités jusqu’à l’enregistrement d’une matrice.

Le convoyeur peut enregistrer sur son téléphone selon les cases autorisées. Les profils chauffeur/convoyeur ne peuvent vendre ou transmettre une position que pour les voyages qui leur sont affectés. Les refus d’encaissement et de remboursement restent distincts. Un gestionnaire de comptes agent ne peut pas modifier les comptes privilégiés ni accorder des actions qu’il ne possède pas.

## Affectations et paie

Le menu Personnel & affectations présente les chauffeurs et convoyeurs séparément, leurs voyages sur sept jours, les heures de voyage enregistrées, les voyages à venir et l’historique des changements. Les chevauchements d’affectations sont refusés. Les heures utilisent les horaires prévus ou les départs/arrivées réels renseignés ; elles ne mesurent pas la fatigue ni le temps de conduite continu.

Le menu Paie permet de fixer un barème par utilisateur : base mensuelle et indemnité par voyage déclaré terminé. La préparation mensuelle fige les montants, ajoute les primes et déduit les retenues/avances saisies. Préparer, valider et enregistrer le paiement sont trois droits distincts. Le paiement est idempotent, protégé contre les doubles clics et les accès concurrents, et crée une seule charge de salaire. Le mode et la référence du paiement réel sont enregistrés. Aucun transfert bancaire n’est exécuté ; les obligations sociales et fiscales restent à appliquer par la comptabilité.

## Conseils IA & alertes

Un menu séparé regroupe Tickets, Courrier et Bagages, avec un résumé sur les tableaux de bord. Il présente les encaissements par agent, leur évolution sur deux périodes comparables, les dossiers anciens, les stocks bas et les échéances de flotte. Il signale les charges non affectées et les tronçons dont la marge indicative est négative.

Les tronçons suivent les dates de départ. Le prix d’un billet est réparti sur les tronçons qu’il couvre, les carnets selon leur valeur par voyage, et les charges du voyage à parts égales faute de distances. Les charges absentes ou non affectées ne sont pas inventées : ces résultats ne constituent pas un bilan comptable.

Les seuils de vitesse, charge hebdomadaire, repos, ancienneté des dossiers et baisse des ventes sont configurables. Une alerte de vitesse exige au moins deux mesures consécutives au-dessus du seuil interne, espacées de dix à cent vingt secondes, avec précision exploitable. Les mesures de plus de cinq minutes sont présentées en historique. Le seuil ne remplace pas les limites routières ; aucune sanction ni modification de planning n’est automatique.

Les alertes calculées fonctionnent sans fournisseur IA. Le bouton de synthèse IA utilise la clé et le modèle configurés sur le serveur ; il transmet uniquement des agrégats anonymisés, sans noms, téléphones, pièces ni coordonnées précises. Sans configuration, il affiche une erreur explicite.

## Vérification et distribution

118 tests serveur, 29 tests JavaScript, test DOM/API des services existants et parcours navigateur sur six largeurs : 320, 360, 390, 430, 768 et 1280 px. Le parcours couvre la vente par photo, le solde, l’embarquement répété, le GPS téléphone/boîtier, les droits du convoyeur, les affectations, les étapes de paie et l’alerte de vitesse. Le lecteur QR est aussi testé avec une image QR décodée réellement. Les vidéos et les pièces du parcours navigateur sont des données de test ; la vérification sur un téléphone physique et un vrai boîtier reste à faire.

L’APK debug porte l’identifiant com.abzora.transfertpos.test et le nom YAM TRANS Test : il s’installe à côté d’une application existante. La variante release conserve l’identifiant de production. Le compte et les données synchronisées restent ceux du serveur ; les saisies hors connexion d’une autre installation doivent y être synchronisées depuis cette installation.
