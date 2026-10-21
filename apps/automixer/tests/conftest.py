"""Without mlx (Linux) the modules in ``mlx_modules.NEEDS_MLX`` are not collected."""

from __future__ import annotations

from mlx_modules import NEEDS_MLX


def _has_mlx() -> bool:
    try:
        import mlx.core  # noqa: F401
    except ImportError:
        return False
    return True


collect_ignore = [] if _has_mlx() else list(NEEDS_MLX)


def pytest_report_header(config):
    if collect_ignore:
        return f"mlx is not importable: not collected here: {', '.join(collect_ignore)}"
    return None
