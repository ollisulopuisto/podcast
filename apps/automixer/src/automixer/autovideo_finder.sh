#!/bin/bash
# autovideo for the files selected in Finder — run by the Quick Action that
# `python -m automixer.finder_action` installs.
#
# Finder starts this with PATH=/usr/bin:/bin:/usr/sbin:/sbin and shows none
# of its output, so everything a terminal would have told you goes to a
# notification and to the log.

PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="${AUTOVIDEO_STATE:-$HOME/Library/Application Support/autovideo/dx.state}"
LOG="${AUTOVIDEO_LOG:-$HOME/Library/Logs/autovideo.log}"

notify() {
    osascript - "$1" "$2" <<'OSA'
on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run
OSA
}

# Without the state dxRevive runs its default model: a valid file at the
# right level, restored with the wrong model.
if [[ ! -f "$STATE" ]]; then
    notify "autovideo: no dxRevive state" \
        "Choose the model once: autovideo <clip> --edit --state \"$STATE\""
    exit 1
fi

mkdir -p "$(dirname "$LOG")"
failed=0
for file in "$@"; do
    name="$(basename "$file")"
    printf '\n=== %s  %s\n' "$(date '+%F %T')" "$file" >> "$LOG"
    if uv run --project "$PROJECT" autovideo "$file" --state "$STATE" >> "$LOG" 2>&1; then
        notify "autovideo done" "$name"
    else
        failed=1
        notify "autovideo FAILED" "$name — see $LOG"
    fi
done
exit "$failed"
