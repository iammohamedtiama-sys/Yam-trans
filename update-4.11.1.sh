#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
TARGET="${1:?Indiquez le commit serveur à déployer}"
cd /opt/yamtrans-sync
test -f .env
test -f docker-compose.yml
dc() { docker compose -p yamtrans-sync -f /opt/yamtrans-sync/docker-compose.yml "$@"; }
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ARRÊT : modifications locales détectées. Envoyez le résultat de git status --short."
  exit 1
fi
test "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' yamtrans-sync-api-1)" = yamtrans-sync
git cat-file -e "${TARGET}^{commit}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="/root/yamtrans-backups/${STAMP}-before-4.11.1"
OLD_COMMIT="$(git rev-parse HEAD)"
OLD_IMAGE="$(docker inspect --format '{{.Image}}' yamtrans-sync-api-1)"
ROLLBACK_IMAGE="yamtrans-sync-api:rollback-${STAMP}"
mkdir -p "$BACKUP"
cp -p .env docker-compose.yml "$BACKUP/"
printf '%s\n' "$OLD_COMMIT" > "$BACKUP/git-commit.txt"
printf '%s\n' "$OLD_IMAGE" > "$BACKUP/docker-image.txt"
docker tag "$OLD_IMAGE" "$ROLLBACK_IMAGE"
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' </dev/null > "$BACKUP/database.dump"
test -s "$BACKUP/database.dump"
dc exec -T db pg_restore --list < "$BACKUP/database.dump" > "$BACKUP/database-contents.txt"
echo "Sauvegarde vérifiée : $BACKUP"
git switch --detach "$TARGET" </dev/null
rollback() {
  git switch --detach "$OLD_COMMIT" </dev/null
  cp -p "$BACKUP/docker-compose.yml" docker-compose.yml
  docker tag "$ROLLBACK_IMAGE" yamtrans-sync-api:latest
  dc up -d --no-deps --no-build --force-recreate api </dev/null
  echo "Version précédente relancée. Sauvegarde : $BACKUP"
}
if ! dc build api </dev/null; then
  git switch --detach "$OLD_COMMIT" </dev/null
  cp -p "$BACKUP/docker-compose.yml" docker-compose.yml
  docker tag "$ROLLBACK_IMAGE" yamtrans-sync-api:latest
  echo "Échec de construction ; le service précédent reste en place."
  exit 1
fi
if ! dc up -d --no-deps --no-build api </dev/null; then rollback; exit 1; fi
OK=0
for ATTEMPT in $(seq 1 30); do
  if HEALTH="$(curl -fsS --connect-timeout 5 --max-time 10 https://sync.print-station.tech/health 2>/dev/null)"; then
    if printf '%s\n' "$HEALTH" | grep -Eq '"version"[[:space:]]*:[[:space:]]*"4\.11\.1"'; then
      printf '%s\n' "$HEALTH"
      OK=1
      break
    fi
  fi
  sleep 2
done
if [ "$OK" != 1 ]; then rollback; exit 1; fi
dc ps </dev/null
echo "SUCCÈS : YAM TRANS 4.11.1 est en ligne."
