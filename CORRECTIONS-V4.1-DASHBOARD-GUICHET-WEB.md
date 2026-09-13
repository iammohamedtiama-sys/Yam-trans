# YAM TRANS v4.1 — Dashboard, billetterie guichet et Web complet

- Interface Web = même SPA métier que l'application : connexion de tous les rôles, mêmes droits et mêmes actions.
- Super admin plateforme : administration société + mode « Ouvrir comme administrateur société » avec retour plateforme.
- Dashboard Courrier multi-filtres : période, agence, agent, statut, origine, destination, type, paiement, recherche.
- Dashboard Tickets : période, ligne, bus, statut, occupation, embarqués, no-show, clients, recette/billet.
- Billetterie guichet : bus, plans VIP/Simple, lignes, arrêts, points de montée/descente, départs, tarifs, équipage, vente siège, paiement, PNR/QR, SMS/WhatsApp, fidélité.
- Client unifié Courrier/Tickets par numéro de téléphone.
- Plan de charge/manifeste : capacité, charge par arrêt, montée/descente, embarquement QR, no-show.
- Front Web construit dans l'image Docker (multi-stage Node + Python), servi sous /app/ ; /admin-web redirige vers /app/.
