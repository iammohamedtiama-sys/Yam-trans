#!/usr/bin/env bash
# Update this existing YamTrans deployment; keep its database and configuration.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v docker >/dev/null
command -v git >/dev/null
[ -f .env ] || { echo 'Configuration .env absente. Utilisez deploy.sh pour une première installation.' >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo 'Placez ce dépôt serveur sur la branche main avant la mise à jour.' >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo 'Des fichiers suivis ont été modifiés. Conservez-les avant de mettre à jour.' >&2; exit 1; }
umask 077
mkdir -p backups
chmod 700 backups
backup_partial="$(mktemp "backups/yamtrans-$(date -u +%Y%m%d-%H%M%S)-XXXXXX.sql.partial")"
trap 'rm -f -- "$backup_partial"' EXIT
# PostgreSQL credentials are expanded inside its own container, never printed.
docker compose exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$backup_partial"
[ -s "$backup_partial" ] || { echo 'La sauvegarde est vide : aucune mise à jour effectuée.' >&2; exit 1; }
backup_final="${backup_partial%.partial}"
mv -- "$backup_partial" "$backup_final"
echo "Sauvegarde PostgreSQL conservée : $backup_final"
git pull --ff-only origin main
docker compose up -d --build api
docker compose exec -T api python -c 'import json,time,urllib.request
for attempt in range(30):
 try:
  data=json.load(urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=3))
  assert data.get("version")=="4.8.2", "Version inattendue"
  print("YamTrans 4.8.2 : serveur opérationnel")
  break
 except Exception:
  if attempt==29: raise SystemExit("Vérification du serveur échouée. La sauvegarde PostgreSQL a été conservée.")
  time.sleep(1)'
