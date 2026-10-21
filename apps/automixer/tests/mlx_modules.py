"""Test modules that cannot even be imported without Apple's mlx.

They import ``mlx.core`` or the in-memory mixer's domain modules (which do) at
the top, so on a machine without mlx (Linux) pytest fails at collection, not
in a test. ``conftest.py`` leaves them out there and says so in the report
header; macOS runs them, and ``test_mlx_modules.py`` proves each one really
does need mlx, so the list cannot hide a module that has stopped needing it.
"""

NEEDS_MLX = (
    "test_analyzer.py",
    "test_balance.py",
    "test_endtoend.py",
    "test_mlx_threads.py",
    "test_new_logic.py",
    "test_plugin_is_shared.py",
    "test_processor.py",
    "test_shared_chain.py",
    "test_video.py",
)
