#!/usr/bin/env bash
set -euo pipefail

VERSION="8.27.0"
DESTINATION="${1:-/tmp/gitleaks}"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64|amd64) ARCH="x64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) echo "unsupported Gitleaks architecture: $ARCH" >&2; exit 1 ;;
esac

case "$OS" in
  linux|darwin) ;;
  *) echo "unsupported Gitleaks operating system: $OS" >&2; exit 1 ;;
esac

ASSET="gitleaks_${VERSION}_${OS}_${ARCH}.tar.gz"
BASE="https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}"
case "$OS/$ARCH" in
  linux/x64) EXPECTED_SHA256="ba75459d765ebc9e940c0123a2d41a29e87be674b5ecaaacd5f82f26009255d5" ;;
  linux/arm64) EXPECTED_SHA256="7df9471047e31316b2b0e21314c6ef0f1704dfbb8220c3b755cfcb9f849510eb" ;;
  darwin/x64) EXPECTED_SHA256="026b9587dff40b264d033c519d6ac8e9b4aa5ae26f86eb58b3c0b440b5cc639d" ;;
  darwin/arm64) EXPECTED_SHA256="809884f52dd94a462dcda6c2c8508c52446db69dd4dc7e1f1e3b14e4eeae9d4f" ;;
  *) echo "unsupported Gitleaks platform: $OS/$ARCH" >&2; exit 1 ;;
esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "${GITLEAKS_ASSET_SOURCE:-}" ]; then
  cp "$GITLEAKS_ASSET_SOURCE" "$TMP/$ASSET"
else
  curl --proto '=https' --tlsv1.2 -fsSL "$BASE/$ASSET" -o "$TMP/$ASSET"
fi
"$SCRIPT_DIR/verify-sha256.sh" "$EXPECTED_SHA256" "$TMP/$ASSET"
tar -xzf "$TMP/$ASSET" -C "$TMP" gitleaks
install -m 0755 "$TMP/gitleaks" "$DESTINATION"
"$DESTINATION" version
