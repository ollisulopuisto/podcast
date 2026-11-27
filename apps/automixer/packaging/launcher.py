"""Frozen entry point. Workers are routed before any AppKit initialization."""
from automixer.mac_gui import main

raise SystemExit(main())
