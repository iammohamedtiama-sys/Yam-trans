# Serveur v3.0 — multi-sociétés + synchronisation robuste

## Tables v3 sans destruction des données v2
Le serveur crée de nouvelles tables (`companies_v3`, `app_users_v3`, `sync_entities_v3`, `shipment_index_v3`, `sequences_v3`) et conserve les anciennes tables. Au premier démarrage, les anciennes entités sont migrées vers la société `YAMTRANS`.

## Réparation des collisions historiques
Les anciennes versions généraient les codes colis sur chaque appareil, ce qui permettait deux `OUA-00001` différents. Au démarrage v3 :
- les doublons historiques sont détectés par société ;
- le plus ancien colis conserve son code ;
- les doublons suivants reçoivent un nouveau code officiel ;
- les paiements/retraits liés par `shipmentId` sont corrigés ;
- l'index public de tracking est reconstruit.

## Réservation de séquences offline
`POST /api/v2/sequences/reserve` réserve un bloc de numéros à un appareil. Le client peut ensuite travailler hors ligne sans générer le même code qu'un autre terminal.

## Synchronisation versionnée
`POST /api/v2/sync` utilise `_serverVersion`. Une écriture basée sur une ancienne version produit un conflit `stale_version` au lieu d'écraser silencieusement la donnée récente.

## Multi-tenant
Toutes les entités v3 sont liées à `company_id`. L'index de tracking a une clé `(company_id, code)`. Deux sociétés peuvent donc avoir chacune `OUA-00001`.

## Authentification
- `POST /api/v2/auth/login`
- Code société + utilisateur + mot de passe.
- Token HMAC signé, valable 30 jours.
- Rôle `platform_admin` pour le Super Super Admin.
- Rôles société : `company_admin`, `superuser`, `admin`, `agency`.

## Administration plateforme
- `POST /api/v2/admin/companies` : création société + premier administrateur.
- `POST /api/v2/admin/users` : création utilisateur société.
- `DELETE /api/v2/admin/users/{id}` : désactivation utilisateur.
- `PUT /api/v2/admin/company/profile` : nom, téléphone, logo.

## Tracking
- `/suivi?company=YAMTRANS&code=OUA-00001`
- `/api/v2/track/YAMTRANS/OUA-00001`
- Timeline étape par étape + point de retrait + Google Maps + branding société.

## Variables d'environnement importantes
Définir en production :
- `TOKEN_SECRET`
- `DEFAULT_ADMIN_PASSWORD`
- `PLATFORM_ADMIN_USER`
- `PLATFORM_ADMIN_PASSWORD`

Le serveur garde `SYNC_API_KEY` comme fallback de `TOKEN_SECRET` pendant la migration pour ne pas casser immédiatement l'installation existante.
