#!/bin/sh
# One command after Homebrew: installs what is missing, signs in where an
# app needs it, and starts the app. Nothing is installed but uv and ffmpeg;
# the app itself runs through uvx from GitHub.
#
#   curl -fsSL https://raw.githubusercontent.com/ollisulopuisto/podcast/main/run.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/ollisulopuisto/podcast/main/run.sh | sh -s -- automixer episode.nhsx
#
# The first argument is the app (default colab-transcribe), the rest go to it.
# PODCAST_REF picks a branch or commit (default main).

set -eu

REPO="git+https://github.com/ollisulopuisto/podcast"
REF="${PODCAST_REF:-main}"
# Piped from curl, stdin is the script itself: sign-in prompts and the apps'
# own interfaces must read from the terminal instead.
TTY="${PODCAST_TTY:-/dev/tty}"

APPS="colab-transcribe autoraffkat automixer automixer-beds autotui autovideo
autoanalyze podcast-magic nhsx-render json-to-text fcp-subs-whisper"

app="${1:-colab-transcribe}"
[ "$#" -gt 0 ] && shift

case "$app" in
  colab-transcribe) dir="colab-transcribe" ;;
  autoraffkat) dir="apps/autoraffkat" ;;
  automixer | automixer-beds | autotui | autovideo | autoanalyze) dir="apps/automixer" ;;
  podcast-magic | nhsx-render | json-to-text) dir="apps/podcast-magic" ;;
  fcp-subs-whisper) dir="apps/fcp-subs-whisper" ;;
  *)
    echo "Unknown app: $app" >&2
    echo "Known apps: $(echo "$APPS" | tr '\n' ' ')" >&2
    exit 2
    ;;
esac

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is needed first. Install it from https://brew.sh, then run this again." >&2
  exit 1
fi

missing=""
command -v uvx >/dev/null 2>&1 || missing="$missing uv"
# colab-transcribe itself needs no ffmpeg, but the other apps do: one setup
# covers them all.
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
if [ -n "$missing" ]; then
  echo "Installing:$missing"
  # shellcheck disable=SC2086 # one word per package
  brew install $missing
fi

source="$REPO@$REF#subdirectory=$dir"
if [ "$dir" = "apps/podcast-magic" ]; then
  # The Whisper engine: Metal on Apple Silicon, faster-whisper elsewhere.
  if [ "$(uname -m)" = "arm64" ]; then extra="mlx"; else extra="faster"; fi
  source="podcast-magic[$extra] @ $source"
fi

# Readable is not enough: without a controlling terminal (a remote session,
# CI) /dev/tty passes -r but fails to open. Try opening it.
if ! (: < "$TTY") 2>/dev/null; then TTY=/dev/stdin; fi

if [ "$app" = "colab-transcribe" ] \
  && [ ! -f "$HOME/.config/colab-cli/token.json" ] \
  && [ ! -f "$HOME/.config/gcloud/application_default_credentials.json" ] \
  && [ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  echo "First run: sign in to Google (open the address it prints, paste the code back here)."
  uvx --from "$source" colab-transcribe --login < "$TTY"
fi

exec uvx --from "$source" "$app" "$@" < "$TTY"
