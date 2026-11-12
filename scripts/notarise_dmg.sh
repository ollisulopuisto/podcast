#!/usr/bin/env bash
# Notarise and staple a signed DMG. Used by build-podcast-magic.yml; the logic
# lives here so tests/test_notarise_dmg.py can run it against stubbed Apple tools.
#
# A tag build without credentials fails (the release promises a notarised DMG);
# a manual build warns and stays signed-only.
set -euo pipefail
DMG_PATH="${1:?usage: notarise_dmg.sh path/to.dmg}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDENTIALS_SCRIPT="${CREDENTIALS_SCRIPT:-$HERE/macos_ci_credentials.py}"

if [ -z "${APPLE_ID:-}" ] || [ -z "${APPLE_APP_PASSWORD:-}" ]; then
  if [ "${GITHUB_REF_TYPE:-}" = tag ]; then
    echo "::error::APPLE_ID / APPLE_APP_PASSWORD puuttuvat; julkaisun pitää olla notarisoitu."
    exit 1
  fi
  echo "::warning::Ei notarisointitunnuksia: artefakti on allekirjoitettu mutta ei notarisoitu."
  exit 0
fi

export KEYCHAIN_PATH="${RUNNER_TEMP:?}/podcast-signing.keychain-db"
export APPLE_TEAM_ID="${APPLE_TEAM_ID:-LWSR8T5392}"
python3 "$CREDENTIALS_SCRIPT" store-notary-credentials
result=$(xcrun notarytool submit "$DMG_PATH" --keychain-profile ci-notary --keychain "$KEYCHAIN_PATH" --wait --timeout 45m --output-format json) || true
echo "$result"
id=$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
status=$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
if [ "$status" != Accepted ]; then
  xcrun notarytool log "$id" --keychain-profile ci-notary --keychain "$KEYCHAIN_PATH"
  exit 1
fi
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"
spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG_PATH"
