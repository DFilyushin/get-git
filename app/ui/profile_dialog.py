"""Диалог добавления/редактирования источника (сервера GitLab или GitHub)."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QComboBox,
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

from app.core import config as config_mod
from app.core.github_client import DEFAULT_API_URL as GITHUB_API_URL
from app.core.provider import PROVIDER_GITHUB, PROVIDER_GITLAB, PROVIDER_TITLES
from app.core.storage import Profile

log = logging.getLogger(__name__)

_URL_HINTS = {
    PROVIDER_GITLAB: "https://gitlab.example.com",
    PROVIDER_GITHUB: GITHUB_API_URL,
}
_TOKEN_HINTS = {
    PROVIDER_GITLAB: "personal access token c правом read_api",
    PROVIDER_GITHUB: "personal access token co scope repo",
}


class ProfileDialog(QDialog):
    """Возвращает отредактированный профиль в self.profile после accept()."""

    def __init__(self, profile: Profile | None = None, parent=None):
        super().__init__(parent)
        self.profile = profile or Profile()
        self.setWindowTitle(
            "Источник репозиториев" if profile else "Новый источник репозиториев"
        )
        self.setMinimumWidth(520)

        form = QFormLayout(self)

        self.name_edit = QLineEdit(self.profile.name)
        self.name_edit.setPlaceholderText("Например: Рабочий GitLab")
        form.addRow("Название:", self.name_edit)

        self.provider_combo = QComboBox()
        for provider in (PROVIDER_GITLAB, PROVIDER_GITHUB):
            self.provider_combo.addItem(PROVIDER_TITLES[provider], provider)
        self.provider_combo.setCurrentIndex(
            self.provider_combo.findData(self.profile.provider)
        )
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Тип сервера:", self.provider_combo)

        self.url_edit = QLineEdit(self.profile.api_url)
        form.addRow("Адрес сервера/API:", self.url_edit)

        self.token_edit = QLineEdit(config_mod.get_profile_token(self.profile.id))
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Access token:", self.token_edit)

        self.dir_edit = QLineEdit(self.profile.base_dir)
        dir_browse = QPushButton("Обзор…")
        dir_browse.clicked.connect(self._browse_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(dir_browse)
        form.addRow("Директория:", dir_row)

        self.key_edit = QLineEdit(self.profile.ssh_key_path)
        key_browse = QPushButton("Обзор…")
        key_browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(key_browse)
        form.addRow("SSH-ключ:", key_row)

        self.jobs_spin = QSpinBox()
        self.jobs_spin.setRange(1, 16)
        self.jobs_spin.setValue(self.profile.parallel_jobs)
        form.addRow("Параллельных операций:", self.jobs_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._on_provider_changed()

    def _current_provider(self) -> str:
        return self.provider_combo.currentData()

    def _on_provider_changed(self) -> None:
        provider = self._current_provider()
        self.url_edit.setPlaceholderText(_URL_HINTS[provider])
        self.token_edit.setPlaceholderText(_TOKEN_HINTS[provider])
        if provider == PROVIDER_GITHUB and not self.url_edit.text().strip():
            self.url_edit.setText(GITHUB_API_URL)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Директория для репозиториев", self.dir_edit.text()
        )
        if path:
            self.dir_edit.setText(path)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите приватный SSH-ключ", self.key_edit.text()
        )
        if path:
            self.key_edit.setText(path)

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if not name or not url:
            QMessageBox.warning(
                self, "Заполните поля", "Название и адрес сервера обязательны."
            )
            return
        try:
            config_mod.set_profile_token(self.profile.id, self.token_edit.text().strip())
        except Exception as exc:  # noqa: BLE001 — ошибка keyring не должна ронять приложение
            log.exception("Не удалось сохранить токен")
            QMessageBox.warning(
                self,
                "Не удалось сохранить токен",
                "Ошибка записи в Диспетчер учётных данных Windows:\n"
                f"{exc}\n\nИсточник не сохранён.",
            )
            return
        self.profile.name = name
        self.profile.provider = self._current_provider()
        self.profile.api_url = url
        self.profile.base_dir = self.dir_edit.text().strip()
        self.profile.ssh_key_path = self.key_edit.text().strip()
        self.profile.parallel_jobs = self.jobs_spin.value()
        self.accept()
