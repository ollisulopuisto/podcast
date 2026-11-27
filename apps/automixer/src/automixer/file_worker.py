"""Child entry point for the desktop's single-file jobs."""
from __future__ import annotations

import argparse
import signal
import sys

from automixer import cli_video


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('target')
    parser.add_argument('--lufs', type=float, default=-16)
    parser.add_argument('--no-plugin', action='store_true', required=True)
    args = parser.parse_args()

    def stop(_signal, _frame):
        # Unwind backend finally blocks, including its unique partial cleanup.
        raise SystemExit(130)

    signal.signal(signal.SIGTERM, stop)
    try:
        if sys.platform == 'darwin':
            from Foundation import (
                NSActivityUserInitiatedAllowingIdleSystemSleep,
                NSProcessInfo,
            )
            process = NSProcessInfo.processInfo()
            token = process.beginActivityWithOptions_reason_(
                NSActivityUserInitiatedAllowingIdleSystemSleep, 'Processing audio',
            )
        else:
            process, token = None, None
        try:
            cli_video.fix_video(args.source, args.target, args.lufs, plugin=None,
                                log=lambda line: print(line, flush=True))
        finally:
            if process is not None:
                process.endActivity_(token)
    except (cli_video.VideoError, OSError) as exc:
        print(str(exc), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
