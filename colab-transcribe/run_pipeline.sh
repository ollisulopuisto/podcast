#!/usr/bin/env bash
set -euo pipefail

# Tämä kuori oli ennen se joka rakensi komennot käsin. Nyt ajuri rakentaa
# ne (`colabtranscribe.driver.plan_commands`), ja tämä jää vain tutun
# kutsun takia: komennoilla on yksi muoto, ei kahta totuutta.
#
#     ./run_pipeline.sh                          # oletukset, remote-preset
#     ./run_pipeline.sh --preset intra-mic       # valitsimet menevät läpi
#
# Vaatii työtilan asennuksen: `uv sync --all-packages` juuresta.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

mkdir -p ./input ./output
exec uv run --directory "$ROOT" colab-transcribe --input ./input --output ./output "$@"
