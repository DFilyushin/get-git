"""Фоновые задачи для QThreadPool: список проектов и клонирование/синхронизация."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from app.core import git_ops
from app.core.gitlab_client import GitLabClient, GitLabError, Project

CANCELLED = "отменено"


class ListSignals(QObject):
    done = Signal(object)  # list[Project]
    failed = Signal(str)


class ProjectListTask(QRunnable):
    def __init__(self, client: GitLabClient):
        super().__init__()
        self.setAutoDelete(False)
        self.client = client
        self.signals = ListSignals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.client.list_projects())
        except GitLabError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — фоновая нить не должна падать молча
            self.signals.failed.emit(f"неожиданная ошибка: {exc}")


class TaskSignals(QObject):
    log = Signal(str)
    finished = Signal(str, bool, str)  # path_with_namespace, ok, сообщение


class RepoTask(QRunnable):
    def __init__(
        self,
        project: Project,
        base_dir: str,
        ssh_key_path: str,
        cancel_event: threading.Event,
    ):
        super().__init__()
        self.setAutoDelete(False)
        self.project = project
        self.base_dir = Path(base_dir)
        self.ssh_key_path = ssh_key_path
        self.cancel_event = cancel_event
        self.signals = TaskSignals()

    def run(self) -> None:
        name = self.project.path_with_namespace
        if self.cancel_event.is_set():
            self.signals.finished.emit(name, False, CANCELLED)
            return
        dest = self.base_dir / Path(*name.split("/"))
        try:
            if (dest / ".git").is_dir():
                self.signals.log.emit(f"{name}: синхронизация…")
                git_ops.sync_repo(dest, self.project.default_branch, self.ssh_key_path)
                self.signals.finished.emit(name, True, "обновлён")
            elif dest.exists() and any(dest.iterdir()):
                raise git_ops.GitError("папка существует, но не является git-репозиторием")
            else:
                self.signals.log.emit(f"{name}: клонирование…")
                git_ops.clone_repo(self.project.ssh_url_to_repo, dest, self.ssh_key_path)
                self.signals.finished.emit(name, True, "клонирован")
        except git_ops.GitError as exc:
            self.signals.finished.emit(name, False, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.signals.finished.emit(name, False, f"неожиданная ошибка: {exc}")
