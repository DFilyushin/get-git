"""Диалог настроек: адрес GitLab, токен, SSH-ключ, параллельность."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

log = logging.getLogger(__name__)

from app.core import config as config_mod
from app.core.config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(480)
        self.config = config

        form = QFormLayout(self)

        self.url_edit = QLineEdit(config.gitlab_url)
        self.url_edit.setPlaceholderText("https://gitlab.example.com")
        form.addRow("Адрес GitLab:", self.url_edit)

        self.token_edit = QLineEdit(config_mod.get_token())
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Access token (read_api):", self.token_edit)

        self.key_edit = QLineEdit(config.ssh_key_path)
        key_browse = QPushButton("Обзор…")
        key_browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(key_browse)
        form.addRow("SSH-ключ:", key_row)

        self.jobs_spin = QSpinBox()
        self.jobs_spin.setRange(1, 16)
        self.jobs_spin.setValue(config.parallel_jobs)
        form.addRow("Параллельных операций:", self.jobs_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите приватный SSH-ключ", self.key_edit.text()
        )
        if path:
            self.key_edit.setText(path)

    def _on_accept(self) -> None:
        url = self.url_edit.text().strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            config_mod.set_token(self.token_edit.text().strip())
        except Exception as exc:  # noqa: BLE001 — ошибка keyring не должна ронять приложение
            log.exception("Не удалось сохранить токен")
            QMessageBox.warning(
                self,
                "Не удалось сохранить токен",
                "Ошибка записи в Диспетчер учётных данных Windows:\n"
                f"{exc}\n\nНастройки не сохранены.",
            )
            return
        self.config.gitlab_url = url
        self.config.ssh_key_path = self.key_edit.text().strip()
        self.config.parallel_jobs = self.jobs_spin.value()
        self.accept()
