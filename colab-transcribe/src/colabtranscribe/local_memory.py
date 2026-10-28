"""Provisional physical-memory eligibility, not a runtime memory-safety test."""
from __future__ import annotations

import platform
import subprocess

MINIMUM_BYTES = 16 * 1024**3


def physical_memory() -> int | None:
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"],
                                    capture_output=True, text=True, check=True, timeout=2)
            value = int(result.stdout.strip())
            return value if value > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def eligible() -> bool:
    memory = physical_memory()
    return memory is not None and memory >= MINIMUM_BYTES
