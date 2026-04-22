from __future__ import annotations

from pathlib import Path

from .config import Settings


def hermes_home(settings: Settings) -> Path:
    return Path(settings.HERMES_HOME)
