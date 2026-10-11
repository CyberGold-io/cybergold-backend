#!/usr/bin/env bash
set -euo pipefail

EXPECTED="${1:?expected SHA-256 is required}"
FILE="${2:?file path is required}"

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL="$(sha256sum "$FILE" | awk '{print $1}')"
else
  ACTUAL="$(shasum -a 256 "$FILE" | awk '{print $1}')"
fi

if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "SHA-256 mismatch for $FILE" >&2
  exit 1
fi
