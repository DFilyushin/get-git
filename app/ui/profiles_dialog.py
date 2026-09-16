"""Диалог управления источниками: список, добавление, изменение, удаление."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.core import config as config_mod
from app.core.provider import PROVIDER_TITLES
from app.core.storage import Database
from app.ui.profile_dialog import ProfileDialog


class ProfilesDialog(QDialog):
    """После закрытия main window перечитывает источники (self.changed)."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.changed = False
        self.setWindowTitle("Источники репозиториев")
        self.setMinimumSize(560, 320)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _: self._edit())
        layout.addWidget(self.list_widget, 1)

        buttons_row = QHBoxLayout()
        add_btn = QPushButton("Добавить…")
        add_btn.clicked.connect(self._add)
        buttons_row.addWidget(add_btn)
        edit_btn = QPushButton("Изменить…")
        edit_btn.clicked.connect(self._edit)
        buttons_row.addWidget(edit_btn)
        delete_btn = QPushButton("Удалить")
        delete_btn.clicked.connect(self._delete)
        buttons_row.addWidget(delete_btn)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        close_box.clicked.connect(self.accept)
        layout.addWidget(close_box)

        self._reload()

    def _reload(self) -> None:
        self.list_widget.clear()
        for profile in self.db.profiles():
            title = PROVIDER_TITLES.get(profile.provider, profile.provider)
            item = QListWidgetItem(f"{profile.name} — {title} ({profile.api_url})")
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.list_widget.addItem(item)

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _add(self) -> None:
        dialog = ProfileDialog(None, self)
        if dialog.exec():
            self.db.save_profile(dialog.profile)
            self.changed = True
            self._reload()

    def _edit(self) -> None:
        profile_id = self._selected_id()
        if not profile_id:
            return
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        dialog = ProfileDialog(profile, self)
        if dialog.exec():
            self.db.save_profile(dialog.profile)
            self.changed = True
            self._reload()

    def _delete(self) -> None:
        profile_id = self._selected_id()
        if not profile_id:
            return
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить источник",
            f"Удалить источник «{profile.name}»?\n"
            "Скачанные репозитории на диске останутся, будут удалены только "
            "настройки, токен и история обновлений.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_profile(profile_id)
        config_mod.delete_profile_token(profile_id)
        self.changed = True
        self._reload()
