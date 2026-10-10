# YAM TRANS v4.6.3 — audit de la discussion avec M. Traoré

## Objet

Cette version compare les demandes exprimées dans la discussion WhatsApp avec les sources mobile, web et serveur de la v4.6.2. Elle corrige en priorité les doublons, les blocages au moment de l’impression et les erreurs visibles dans les captures.

## Corrections appliquées

### 1. Doubles enregistrements

- Verrou immédiat du bouton pendant la création d’un Courrier, d’un Bagage ou d’un Billet.
- Contrôle par empreinte fonctionnelle pendant 2 minutes : utilisateur, client, trajet, montant, contenu, siège ou voyage selon le service.
- Si l’opération existe déjà, la seconde création est refusée et l’opération existante est proposée pour impression.
- Le contrôle serveur de 120 secondes reste actif pour bloquer aussi un doublon arrivé par synchronisation.
- Les formulaires sont vidés après une création réussie.
- Le bouton est réactivé pour permettre une nouvelle opération différente sans attendre deux minutes.

### 2. Blocage du formulaire Courrier sous Windows

Le code utilisait une variable globale `fee` qui n’existait pas de manière fiable dans une application compilée. La valeur est maintenant lue directement depuis le formulaire puis conservée dans une variable locale. Cela corrige l’erreur au clic sur « Confirmer et imprimer » et évite que l’opérateur reclique plusieurs fois.

### 3. Export PDF

Les fonctions suivantes étaient appelées mais absentes de la v4.6.2 :

- conversion des couleurs hexadécimales ;
- application des couleurs dans jsPDF ;
- chargement et détection du format du logo ;
- sauvegarde, téléchargement ou partage d’un PDF/CSV.

Elles ont été restaurées. Les rapports Courrier, la comptabilité, les bordereaux, les manifestes Bagages, les billets et les exports clients peuvent de nouveau générer leurs fichiers.

### 4. Bouton retour Super Admin

L’appel erroné `lightCompany(...)` a été remplacé par `lightweightCompany(...)`. Le retour depuis une société vers la plateforme ne déclenche plus l’erreur « lightCompany is not defined ».

### 5. Billetterie

- Impression réelle du billet via Bluetooth ESC/POS ou service d’impression natif.
- PDF de secours si l’imprimante n’est pas disponible.
- Fenêtre d’actions d’un billet restaurée : détail, impression et PDF.
- Fenêtre « Plan de charge » restaurée.
- Anti-double vente ajouté.
- Sièges occupés affichés clairement en rouge.
- Formulaire vidé après émission.

### 6. Bagages

- Anti-double enregistrement ajouté aux deux formulaires Bagages.
- Formulaire vidé après enregistrement.
- Pour un agent :
  - après l’arrivée, l’étiquette n’est plus réimprimable ;
  - après le retrait, ni le reçu ni l’étiquette ne sont réimprimables.
- Un administrateur conserve la possibilité de réimprimer pour traitement exceptionnel.
- Une opération annulée n’affiche plus les actions d’impression.
- Les contrôles sont appliqués à l’affichage et au clic.

### 7. Étiquette Courrier

La mention demandée est maintenant imprimée dans les versions HTML, Bluetooth et PDF :

> Scanner le QR pour charger le colis ou effectuer le retrait.

Le PDF de l’étiquette a aussi été recomposé pour tenir réellement dans les formats 80 × 80 mm et 58 × 57 mm.

### 8. Mot de passe utilisateur

Le formulaire et l’API de modification ont été contrôlés ensemble. Le nouveau mot de passe est chiffré côté serveur. Un test d’intégration confirme que l’ancien mot de passe est refusé et que le nouveau est accepté.

## Fonctions déjà présentes et conservées

- fonctionnement hors connexion et synchronisation ;
- multi-sociétés et séparation des données ;
- QR de suivi, retrait et chargement ;
- bordereaux Courrier et manifestes Bagages ;
- arrivée automatique des bagages d’un manifeste ;
- CRM clients, fidélité, campagnes et exports ;
- comptabilité et filtrage par période/agence/agent ;
- conservation limitée des photos ;
- restriction des destinations par agence ;
- annulation antifraude et exclusion des montants annulés ;
- contrôle serveur des doublons.

## Points qui nécessitent un autre projet ou un accès de publication

- Le code source de l’installateur Windows/Electron n’est pas présent dans les archives reçues. Le portail web est corrigé, mais un nouvel exécutable Windows ne peut pas être reconstruit depuis ces deux archives seules.
- La publication Play Store nécessite le compte Google Play Console, la clé de signature et la fiche de publication. Le projet Android est synchronisé et prêt pour une génération signée.

## Vérifications réalisées

- analyse JavaScript `no-undef` : aucune variable ou fonction manquante ;
- compilation Vite mobile : réussie ;
- synchronisation Capacitor Android : réussie ;
- compilation Vite web : réussie ;
- compilation Python : réussie ;
- test API de santé : version 4.6.3 ;
- test connexion et changement de mot de passe : réussi ;
- test serveur de rejet d’un double enregistrement : réussi.

