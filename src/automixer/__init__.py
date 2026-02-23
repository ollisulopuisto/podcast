import importlib.metadata

try:
    __version__ = importlib.metadata.version("automixer")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"
