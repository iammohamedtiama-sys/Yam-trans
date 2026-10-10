# Déploiement v3 sur le VPS existant

Avant le premier redémarrage v3, compléter `.env` sans supprimer les variables PostgreSQL existantes :

```env
TOKEN_SECRET=une-cle-tres-longue-et-aleatoire
DEFAULT_ADMIN_PASSWORD=un-mot-de-passe-fort
PLATFORM_ADMIN_USER=platform
PLATFORM_ADMIN_PASSWORD=un-autre-mot-de-passe-tres-fort
DEFAULT_COMPANY_CODE=YAMTRANS
```

Puis :

```bash
cd /opt/yamtrans-sync
git fetch origin
git reset --hard origin/main
docker compose down
docker compose up -d --build
sleep 8
docker compose ps
curl -i http://127.0.0.1:8091/health
```

Ne jamais supprimer le volume `yamtrans_pgdata` pendant cette migration.
