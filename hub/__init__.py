"""Personal Hub."""

from importlib.metadata import version

# une seule version, celle de pyproject.toml : l'image, /api/health et le tag git la partagent
__version__ = version("personal-hub")
