#!/usr/bin/env bash
# Reuse the exact green protected-branch authority formerly checked by Ops.
set -Eeuo pipefail

case "${RELEASE_SOURCE_BRANCH:?RELEASE_SOURCE_BRANCH is required}" in
  dev) target=sandbox ;;
  main) target=mainnet ;;
  *) echo 'Image releases require Backend dev or main.' >&2; exit 1 ;;
esac
: "${RELEASE_SOURCE_COMMIT:?RELEASE_SOURCE_COMMIT is required}"
: "${RELEASE_CI_RUN_ID:?RELEASE_CI_RUN_ID is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
repository=CyberGold-io/cybergold-backend
if [[ "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}" != "$repository" ]]; then
  echo 'Image releases require the canonical CyberGold Backend repository.' >&2; exit 1
fi

run="$(gh api "/repos/$repository/actions/runs/$RELEASE_CI_RUN_ID")"
require_run() {
  if ! jq -e "$1" <<<"$run" >/dev/null; then
    echo "$2" >&2; exit 1
  fi
}
require_run '.event == "push"' 'The Backend CI run must be a push run.'
require_run '.path == ".github/workflows/ci.yml"' 'The Backend CI run must use ci.yml.'
require_run '.status == "completed"' 'The Backend CI run has not completed.'
require_run '.conclusion == "success"' 'The Backend CI run did not succeed.'
require_run ".head_branch == \"$RELEASE_SOURCE_BRANCH\"" 'The Backend CI run has the wrong source branch.'
require_run ".head_sha == \"$RELEASE_SOURCE_COMMIT\"" 'The Backend CI run has the wrong source commit.'
current="$(gh api "/repos/$repository/git/ref/heads/$RELEASE_SOURCE_BRANCH" --jq .object.sha)"
if [[ "$current" != "$RELEASE_SOURCE_COMMIT" ]]; then
  echo 'The requested Backend commit is no longer the current mapped branch head.' >&2; exit 1
fi
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'target=%s\n' "$target" >>"$GITHUB_OUTPUT"
fi
