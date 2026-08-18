"""Доступ к ресурсам приложения из исходников и из PyInstaller-сборки."""
from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Путь к ресурсу: в frozen-сборке — из распакованного бандла, иначе из корня проекта."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(__file__).resolve().parent.parent
    return Path(base) / relative
