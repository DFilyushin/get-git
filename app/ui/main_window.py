"""Главное окно: источник, директория, список репозиториев, лог операций."""
from __future__ import annotations

import functools
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import config as config_mod
from app.core import git_ops
from app.core.provider import PROVIDER_TITLES, Project, make_client
from app.core.storage import Database, Profile, SyncState, migrate_legacy
from app.core.sync_manager import CANCELLED, ProjectListTask, RepoTask
from app.ui.about_dialog import AboutDialog
from app.ui.profiles_dialog import ProfilesDialog

log = logging.getLogger(__name__)

COL_REPO, COL_GROUP, COL_LOCAL, COL_UPDATED, COL_STATUS = range(5)
DATE_FORMAT = "%d.%m.%Y %H:%M"
NO_ACCESS = "нет доступа к коду"


def guarded(func):
    """Слот не должен ронять приложение: ошибка — в лог и в окно сообщения."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка в %s", func.__name__)
            try:
                self.append_log(f"ОШИБКА: {exc}")
            except Exception:  # noqa: BLE001
                pass
            QMessageBox.critical(
                self, "Ошибка", f"Непредвиденная ошибка:\n{exc}\n\nПодробности — в логе."
            )

    return wrapper


class MainWindow(QMainWindow):
    def __init__(self, database: Database | None = None):
        super().__init__()
        self.setWindowTitle("Get-Git — зеркала репозиториев GitLab/GitHub")
        self.resize(980, 700)

        self.db = database or Database()
        migrated = migrate_legacy(self.db)

        self.profile: Profile | None = None
        self.state: SyncState | None = None
        self.projects: list[Project] = []
        self.pool = QThreadPool(self)
        self.cancel_event = threading.Event()
        self._tasks: list = []  # ссылки на задачи, пока живы их сигналы
        self._row_items: dict[str, QTableWidgetItem] = {}
        self._projects_by_name: dict[str, Project] = {}
        self._list_profile_id = ""  # источник, для которого запрошен список
        self._total = 0
        self._done = 0
        self._errors = 0
        self._running = False

        self._build_ui()
        self.append_log("Приложение запущено")
        if migrated:
            self.append_log(
                "Настройки перенесены из config.json в базу данных (getgit.db)"
            )
        self._reload_profiles(self.db.get_setting("active_profile"))

    # ---------- UI ----------

    def _build_ui(self) -> None:
        help_menu = self.menuBar().addMenu("Справка")
        about_action = help_menu.addAction("О программе…")
        about_action.triggered.connect(self._show_about)

        central = QWidget()
        layout = QVBoxLayout(central)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Источник:"))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        source_row.addWidget(self.profile_combo, 1)
        self.profiles_btn = QPushButton("Источники…")
        self.profiles_btn.clicked.connect(self._open_profiles)
        source_row.addWidget(self.profiles_btn)
        layout.addLayout(source_row)

        top = QHBoxLayout()
        top.addWidget(QLabel("Директория:"))
        self.dir_edit = QLineEdit()
        self.dir_edit.editingFinished.connect(self._save_dir)
        top.addWidget(self.dir_edit, 1)
        browse_btn = QPushButton("Обзор…")
        browse_btn.clicked.connect(self._browse_dir)
        top.addWidget(browse_btn)
        layout.addLayout(top)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("Обновить список")
        self.refresh_btn.clicked.connect(self.refresh_list)
        buttons.addWidget(self.refresh_btn)
        self.update_btn = QPushButton("Обновить")
        self.update_btn.clicked.connect(self.update_all)
        buttons.addWidget(self.update_btn)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        self.show_unavailable_cb = QCheckBox("Показывать недоступные репозитории")
        self.show_unavailable_cb.setToolTip(
            "Репозитории, код которых недоступен вашей роли"
        )
        self.show_unavailable_cb.setChecked(
            self.db.get_setting("show_unavailable", "1") == "1"
        )
        self.show_unavailable_cb.toggled.connect(self._toggle_unavailable)
        buttons.addWidget(self.show_unavailable_cb)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Репозиторий", "Группа", "Локально", "Обновлено", "Статус"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_REPO, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_GROUP, QHeaderView.ResizeMode.Stretch)
        for col in (COL_LOCAL, COL_UPDATED, COL_STATUS):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._open_in_explorer)
        layout.addWidget(self.table, 3)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Готово")

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {message}")
        log.info(message)

    # ---------- источники ----------

    def _reload_profiles(self, select_id: str = "") -> None:
        profiles = self.db.profiles()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in profiles:
            title = PROVIDER_TITLES.get(profile.provider, profile.provider)
            self.profile_combo.addItem(f"{profile.name} ({title})", profile.id)
        index = max(self.profile_combo.findData(select_id), 0)
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)

        if not profiles:
            self.profile = None
            self.state = None
            self.projects = []
            self.dir_edit.setText("")
            self._populate_table()
            self.append_log("Добавьте источник репозиториев — кнопка «Источники…»")
            return
        self._activate_profile(self.profile_combo.currentData())

    def _activate_profile(self, profile_id: str) -> None:
        profile = self.db.get_profile(profile_id)
        if profile is None:
            return
        self.profile = profile
        self.state = SyncState(self.db, profile.id)
        self.pool.setMaxThreadCount(profile.parallel_jobs)
        self.db.set_setting("active_profile", profile.id)
        self.dir_edit.setText(profile.base_dir)
        self.projects = []
        self._populate_table()
        if profile.api_url and config_mod.get_profile_token(profile.id):
            self.refresh_list()
        else:
            self.append_log(
                f"У источника «{profile.name}» не заданы адрес или токен — "
                "откройте «Источники…»"
            )

    @guarded
    def _on_profile_changed(self, index: int) -> None:
        profile_id = self.profile_combo.itemData(index)
        if profile_id:
            self._activate_profile(profile_id)

    @guarded
    def _open_profiles(self) -> None:
        dialog = ProfilesDialog(self.db, self)
        dialog.exec()
        if dialog.changed:
            current = self.profile.id if self.profile else ""
            self._reload_profiles(current)

    # ---------- действия ----------

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Директория для репозиториев", self.dir_edit.text()
        )
        if path:
            self.dir_edit.setText(path)
            self._save_dir()

    def _save_dir(self) -> None:
        if self.profile is None:
            return
        base_dir = self.dir_edit.text().strip()
        if base_dir != self.profile.base_dir:
            self.profile.base_dir = base_dir
            self.db.save_profile(self.profile)
            self._populate_table()

    @guarded
    def _toggle_unavailable(self, checked: bool) -> None:
        self.db.set_setting("show_unavailable", "1" if checked else "0")
        self._populate_table()

    @guarded
    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _open_in_explorer(self) -> None:
        row = self.table.currentRow()
        base_dir = self.dir_edit.text().strip()
        if row < 0 or not base_dir:
            return
        name = self.table.item(row, COL_REPO).data(Qt.ItemDataRole.UserRole)
        dest = Path(base_dir) / Path(*name.split("/"))
        if dest.is_dir():
            os.startfile(dest)  # noqa: S606 — открытие локальной папки в Проводнике

    @guarded
    def refresh_list(self) -> None:
        if self.profile is None:
            self.append_log("Источник не выбран — откройте «Источники…»")
            return
        token = config_mod.get_profile_token(self.profile.id)
        if not self.profile.api_url or not token:
            self.append_log(
                f"У источника «{self.profile.name}» не заданы адрес или токен — "
                "откройте «Источники…»"
            )
            return
        self.refresh_btn.setEnabled(False)
        self.statusBar().showMessage("Запрашиваю список репозиториев…")
        self.append_log(f"{self.profile.name}: запрашиваю список репозиториев…")
        self._list_profile_id = self.profile.id
        task = ProjectListTask(make_client(self.profile, token))
        task.signals.done.connect(self._on_projects)
        task.signals.failed.connect(self._on_projects_failed)
        self._tasks.append(task)
        self.pool.start(task)

    @guarded
    def _on_projects(self, projects: list[Project]) -> None:
        self.refresh_btn.setEnabled(True)
        self.statusBar().showMessage("Готово")
        if self.profile is None or self.profile.id != self._list_profile_id:
            return  # источник переключили, пока шёл запрос
        self.projects = projects
        no_access = sum(1 for p in projects if not p.can_download)
        message = f"{self.profile.name}: доступно репозиториев — {len(projects)}"
        if no_access:
            message += f" (из них без доступа к коду: {no_access})"
        self.append_log(message)
        self._populate_table()

    def _on_projects_failed(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.statusBar().showMessage("Ошибка")
        self.append_log(f"ОШИБКА: {message}")

    @guarded
    def update_all(self) -> None:
        if self.profile is None:
            self.append_log("Источник не выбран — откройте «Источники…»")
            return
        if not self.projects:
            self.append_log("Список репозиториев пуст — нажмите «Обновить список»")
            return
        base_dir = self.dir_edit.text().strip()
        if not base_dir:
            self.append_log("Укажите директорию для репозиториев")
            return
        available = [p for p in self.projects if p.can_download]
        skipped = len(self.projects) - len(available)
        if skipped:
            self.append_log(f"Пропущено репозиториев без доступа к коду: {skipped}")
        if not available:
            self.append_log("Нет ни одного репозитория, доступного для скачивания")
            return
        if base_dir != self.profile.base_dir:
            self.profile.base_dir = base_dir
            self.db.save_profile(self.profile)
        Path(base_dir).mkdir(parents=True, exist_ok=True)

        self.cancel_event.clear()
        self._tasks = [t for t in self._tasks if isinstance(t, ProjectListTask)]
        self._total = len(available)
        self._done = 0
        self._errors = 0
        self.progress.setRange(0, self._total)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self._running = True
        self._set_busy(True)
        self.append_log(
            f"{self.profile.name}: начинаю обновление {self._total} репозиториев…"
        )

        for project in available:
            task = RepoTask(
                project, base_dir, self.profile.ssh_key_path, self.cancel_event
            )
            task.signals.log.connect(self.append_log)
            task.signals.finished.connect(self._on_repo_done)
            self._tasks.append(task)
            self.pool.start(task)

    @guarded
    def _on_repo_done(self, name: str, ok: bool, message: str) -> None:
        self._done += 1
        self.progress.setValue(self._done)
        if ok:
            if self.state is not None:
                self.state.record(name, True, message)
            self.append_log(f"{name}: {message}")
        elif message == CANCELLED:
            self.append_log(f"{name}: {CANCELLED}")
        else:
            self._errors += 1
            if self.state is not None:
                self.state.record(name, False, f"ошибка: {message}")
            self.append_log(f"ОШИБКА {name}: {message}")
        self._update_row(name)
        if self._done >= self._total:
            self._running = False
            self._set_busy(False)
            self.progress.setVisible(False)
            summary = f"Готово: обновлено {self._done - self._errors}, ошибок {self._errors}"
            if self.cancel_event.is_set():
                summary += " (операция была отменена)"
            self.append_log(summary)
            self.statusBar().showMessage(summary)

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_btn.setEnabled(False)
        self.append_log("Отмена: ожидаю завершения уже запущенных операций…")

    def closeEvent(self, event) -> None:
        if self._running:
            answer = QMessageBox.question(
                self,
                "Синхронизация не завершена",
                "Идёт обновление репозиториев. Прервать и выйти?\n"
                "Незавершённые операции будут остановлены.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.shutdown()
        event.accept()

    def shutdown(self) -> bool:
        """Останавливает фоновые задачи и git-процессы. True — пул завершился чисто."""
        self.cancel_event.set()
        self.pool.clear()  # снять с очереди ещё не начатые задачи
        git_ops.terminate_all()
        return self.pool.waitForDone(5000)

    def _set_busy(self, busy: bool) -> None:
        self.update_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.profiles_btn.setEnabled(not busy)
        self.profile_combo.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.statusBar().showMessage("Синхронизация…" if busy else "Готово")

    # ---------- таблица ----------

    def _populate_table(self) -> None:
        show_unavailable = self.show_unavailable_cb.isChecked()
        visible = [p for p in self.projects if p.can_download or show_unavailable]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        self._row_items = {}
        self._projects_by_name = {p.path_with_namespace: p for p in self.projects}
        for row, project in enumerate(visible):
            namespace, _, short_name = project.path_with_namespace.rpartition("/")
            repo_item = QTableWidgetItem(short_name or project.path_with_namespace)
            repo_item.setData(Qt.ItemDataRole.UserRole, project.path_with_namespace)
            repo_item.setToolTip(project.ssh_url_to_repo)
            self.table.setItem(row, COL_REPO, repo_item)
            self.table.setItem(row, COL_GROUP, QTableWidgetItem(namespace))
            for col in (COL_LOCAL, COL_UPDATED, COL_STATUS):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)
            self._row_items[project.path_with_namespace] = repo_item
            self._update_row(project.path_with_namespace)
        self.table.setSortingEnabled(True)

    def _update_row(self, name: str) -> None:
        repo_item = self._row_items.get(name)
        if repo_item is None:
            return
        row = repo_item.row()
        base_dir = self.dir_edit.text().strip()
        local = False
        if base_dir:
            dest = Path(base_dir) / Path(*name.split("/"))
            local = (dest / ".git").is_dir()
        self.table.item(row, COL_LOCAL).setText("✔" if local else "нет")
        last = self.state.last_sync(name) if self.state else None
        self.table.item(row, COL_UPDATED).setText(last.strftime(DATE_FORMAT) if last else "—")
        project = self._projects_by_name.get(name)
        if project is not None and not project.can_download:
            self.table.item(row, COL_STATUS).setText(NO_ACCESS)
        else:
            self.table.item(row, COL_STATUS).setText(
                self.state.last_result(name) if self.state else ""
            )
