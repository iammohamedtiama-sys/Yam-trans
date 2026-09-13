# Yam-Trans Serveur v3.3 — Administration plateforme

Nouveaux endpoints plateforme :
- GET /api/v2/platform/stats : statistiques globales et par société.
- PUT /api/v2/admin/companies/{company_id} : activation/désactivation et mise à jour plateforme.
- POST /api/v2/admin/companies/{company_id}/logo : téléversement logo en data URL image contrôlée.
- DELETE /api/v2/admin/companies/{company_id} : suppression complète d'une société et de ses données.

La société par défaut est protégée contre la suppression définitive.
Les listes de sociétés destinées au Super Super Admin n'embarquent plus les logos Base64 afin d'éviter de gonfler le cache local.
