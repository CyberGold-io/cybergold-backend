#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
source_dir="${1:?source directory}"
image_tag="${2:?local image tag}"
source_commit="${CG_SOURCE_COMMIT:-}"
if [[ -z "$source_commit" ]]; then
  source_commit="$(python3 - "$source_dir" <<'SOURCE_ID'
import json, os, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
try:
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
except FileNotFoundError:
    top = None
if top is not None and top.returncode == 0 and os.path.realpath(top.stdout.strip()) == os.path.realpath(root):
    print(subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip())
else:
    info = root / "source-info.json"
    versions = json.loads(info.read_text()).get("sourceVersions", []) if info.exists() else []
    print(versions[0] if versions else "")
SOURCE_ID
)"
fi
DOCKER_BUILDKIT=1 docker build --platform linux/amd64 \
  --file "$source_dir/Dockerfile" \
  --build-arg "CYBERGOLD_BACKEND_COMMIT=$source_commit" \
  --tag "$image_tag" "$source_dir"
