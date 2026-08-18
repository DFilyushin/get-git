"""Окно «О программе»."""
from __future__ import annotations

import platform

import PySide6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from app import __version__
from app.core.config import app_data_dir

REPO_URL = "https://github.com/DFilyushin/get-git"


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        icon_label = QLabel()
        icon_label.setPixmap(self.windowIcon().pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        top.addWidget(icon_label)

        logs_uri = (app_data_dir() / "logs").as_uri()
        text = QLabel(
            f"<h2 style='margin-bottom:2px'>Get-Git</h2>"
            f"<p style='margin-top:0'>Версия {__version__}</p>"
            "<p>Зеркалирование доступных вам репозиториев корпоративного GitLab "
            "в локальную директорию: клонирование по SSH и полная синхронизация "
            "веток без коммитов и пушей.</p>"
            f"<p>Python {platform.python_version()} · PySide6 {PySide6.__version__}</p>"
            f"<p><a href='{REPO_URL}'>Исходный код на GitHub</a><br>"
            f"<a href='{logs_uri}'>Папка логов</a></p>"
        )
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        top.addWidget(text, 1)
        layout.addLayout(top)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)
