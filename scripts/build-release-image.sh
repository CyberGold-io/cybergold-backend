#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
: "${RELEASE_SOURCE_COMMIT:?RELEASE_SOURCE_COMMIT is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
DOCKER_BUILDKIT=1 docker build --platform linux/amd64 \
  --file Dockerfile \
  --build-arg "CYBERGOLD_BACKEND_COMMIT=$RELEASE_SOURCE_COMMIT" \
  --label "io.cybergold.backend.commit=$RELEASE_SOURCE_COMMIT" \
  --label "io.cybergold.backend.indexer-snapshot-source-sha256=$(node scripts/snapshot-source-identity.mjs)" \
  --label "org.opencontainers.image.source=https://github.com/CyberGold-io/cybergold-backend" \
  --label "org.opencontainers.image.revision=$RELEASE_SOURCE_COMMIT" \
  --iidfile "$RUNNER_TEMP/backend-image-id" .
image_id="$(cat "$RUNNER_TEMP/backend-image-id")"
archive_name="backend-image-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.docker.tar"
archive_path="$RUNNER_TEMP/$archive_name"
docker image save --output "$archive_path" "$image_id"
printf 'archive_path=%s\narchive_name=%s\nconfig_image_id=%s\n' \
  "$archive_path" "$archive_name" "$image_id" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
