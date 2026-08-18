"""Логирование и перехват аварий.

- app.log — обычный лог с ротацией;
- crash.log — faulthandler для нативных падений (Qt, keyring, DLL);
- sys.excepthook / threading.excepthook — трассировки необработанных исключений.
Всё в %APPDATA%\\GetGit\\logs\\.
"""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from app.core.config import app_data_dir

log = logging.getLogger(__name__)

_crash_file = None  # держим файл открытым, пока жив faulthandler


def setup_logging() -> None:
    global _crash_file
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    try:
        _crash_file = open(log_dir / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file)
    except OSError:
        pass

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    log.critical("Необработанная ошибка", exc_info=(exc_type, exc_value, exc_tb))
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                "Непредвиденная ошибка",
                f"{exc_type.__name__}: {exc_value}\n\nПодробности — в логе:\n"
                f"{app_data_dir() / 'logs' / 'app.log'}",
            )
    except Exception:  # noqa: BLE001 — показ окна не должен маскировать исходную ошибку
        pass


def _thread_excepthook(args) -> None:
    log.critical(
        "Необработанная ошибка в фоновой нити %s",
        getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
