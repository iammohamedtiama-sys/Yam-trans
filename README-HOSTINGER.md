# Serveur Yam-Trans — Hostinger VPS

Ce dossier est indépendant de l'APK et de l'application Windows. Il contient l'API centrale, PostgreSQL et la page publique de suivi.

## Fonctions
- Synchronisation bidirectionnelle des colis, clients, bordereaux, retraits, dépenses, agences, utilisateurs, lignes, stations, véhicules et horaires.
- Fonctionnement local-first côté Android/Windows : une coupure Internet n'empêche pas la saisie ; les données remontent au prochain accès réseau.
- Page publique `/suivi?code=OUA-00001`.
- API publique limitée `/api/v1/track/OUA-00001` qui n'expose ni montants ni pièces d'identité.
- API `/api/v1/sync` protégée par `X-API-Key`.

## Déploiement rapide
```bash
sudo mkdir -p /opt/yamtrans-sync
sudo chown -R $USER:$USER /opt/yamtrans-sync
cd /opt/yamtrans-sync
# copier ici le contenu de ce dossier
cp .env.example .env
nano .env
./deploy.sh
```

Le service écoute seulement sur `127.0.0.1:8091`. Nginx doit publier le domaine HTTPS.

## Nginx
Copier `nginx/yamtrans-sync.conf` dans `/etc/nginx/sites-available/yamtrans-sync`, adapter `server_name`, puis :
```bash
sudo ln -sf /etc/nginx/sites-available/yamtrans-sync /etc/nginx/sites-enabled/yamtrans-sync
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d sync.yam-trans.com
```

## Configuration dans Android et Windows
Dans le compte Super utilisateur :
- URL du serveur : `https://sync.yam-trans.com`
- Clé API : même valeur que `SYNC_API_KEY` dans `.env`
- Activer la synchronisation + synchronisation automatique.
- URL publique de suivi : `https://sync.yam-trans.com/suivi`

Les SMS peuvent alors construire un lien du type :
`https://sync.yam-trans.com/suivi?code=OUA-00001`
