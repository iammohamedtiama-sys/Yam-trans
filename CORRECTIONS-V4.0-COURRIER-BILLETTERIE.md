# YAM TRANS Serveur v4.0 — Multi-modules + Web Admin

## Modules par société
Le Super Super Admin peut autoriser indépendamment :
- Courrier / Colis
- Tickets de transport
- SMS
- WhatsApp

Les utilisateurs reçoivent ensuite des droits limités aux modules réellement activés pour leur société.

## Billetterie synchronisée
Nouveaux types synchronisés : tickets, bus, lignes, départs, embarquements, clients fidélité, promotions, remboursements et journaux de notifications.

## Communications serveur
- Endpoint d'envoi SMS/WhatsApp.
- Configuration fournisseur conservée côté serveur.
- Journalisation des succès/échecs et statistiques par société.

## Console web Super Super Admin
Disponible sur `/admin-web`.
Elle permet d'ouvrir chaque société et de consulter/gérer :
- statistiques globales ;
- utilisateurs et réinitialisation de mot de passe ;
- activité Courrier ;
- activité Tickets ;
- droits de modules ;
- SMS/WhatsApp et fournisseurs ;
- journal des opérations.

## API publique ticket
Le lien public `/ticket?company=CODE&pnr=PNR&key=TOKEN` permet au voyageur d'accéder à son billet depuis un lien reçu par messagerie.
