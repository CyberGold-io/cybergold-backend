#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:?publication target}"
archive="${2:?current-run image archive}"
case "$target" in
  sandbox|mainnet) repository="ghcr.io/cybergold-io/cybergold-backend-b2b-$target" ;;
  *) echo 'Unknown backend image target.' >&2; exit 2 ;;
esac
image_id="${CONFIG_IMAGE_ID:?CONFIG_IMAGE_ID is required}"
docker image load --input "$archive"
docker image inspect "$image_id" >/dev/null

# Reuse the exact successful push run and current branch-head authority.
bash "$root/scripts/require-image-release-authority.sh"

cleanup() {
  docker logout ghcr.io >/dev/null 2>&1 || true
  rm -f -- "${DOCKER_CONFIG:?DOCKER_CONFIG is required}/config.json"
}
trap cleanup EXIT
mkdir -p "${DOCKER_CONFIG:?DOCKER_CONFIG is required}"
printf '%s' "${GHCR_TOKEN:?GHCR_TOKEN is required}" | docker login ghcr.io \
  --username "${GITHUB_ACTOR:?GITHUB_ACTOR is required}" --password-stdin
unset GHCR_TOKEN
tag="backend-${RELEASE_SOURCE_COMMIT}-${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}-${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"
docker tag "$image_id" "$repository:$tag"
output="$(docker push "$repository:$tag")"
digest="$(awk -v expected="$tag" -f "$root/scripts/parse-docker-push-digest.awk" <<<"$output")"
reference="$repository@$digest"

mkdir -p "$root/out/ghcr-publication"
jq -n --arg target "$target" --arg imageReference "$reference" \
  --arg configImageId "$image_id" --arg sourceRepository "CyberGold-io/cybergold-backend" \
  --arg sourceCommit "$RELEASE_SOURCE_COMMIT" --arg sourceCiRunId "$RELEASE_CI_RUN_ID" \
  --arg workflowRunId "$GITHUB_RUN_ID" --arg workflowRunAttempt "$GITHUB_RUN_ATTEMPT" \
  '{target:$target,imageReference:$imageReference,configImageId:$configImageId,sourceRepository:$sourceRepository,sourceCommit:$sourceCommit,sourceCiRunId:$sourceCiRunId,workflowRunId:$workflowRunId,workflowRunAttempt:$workflowRunAttempt}' \
  >"$root/out/ghcr-publication/backend-$target.json" || echo 'Could not save the publication troubleshooting record.' >&2
printf 'image_reference=%s\n' "$reference" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
# Publish discovery only after the immutable image is available.
docker tag "$image_id" "$repository:desired"
output="$(docker push "$repository:desired")"
desired_digest="$(awk -v expected=desired -f "$root/scripts/parse-docker-push-digest.awk" <<<"$output")"
if [[ "$desired_digest" != "$digest" ]]; then
  echo 'The desired tag push returned a different manifest digest.' >&2; exit 1
fi
printf 'Published %s\n' "$reference"
