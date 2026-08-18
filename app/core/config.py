"""Конфигурация приложения и состояние синхронизации.

Конфиг и состояние хранятся в %APPDATA%\\GetGit\\, personal access token —
в Windows Credential Manager (через keyring).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import keyring
from keyring import errors as keyring_errors

APP_NAME = "GetGit"
KEYRING_SERVICE = "GetGit-GitLab"
KEYRING_USER = "token"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    directory = Path(base) / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _config_path() -> Path:
    return app_data_dir() / "config.json"


def _state_path() -> Path:
    return app_data_dir() / "state.json"


@dataclass
class AppConfig:
    base_dir: str = ""
    gitlab_url: str = ""
    ssh_key_path: str = str(Path.home() / ".ssh" / "id_ed25519")
    parallel_jobs: int = 4

    @classmethod
    def load(cls) -> "AppConfig":
        path = _config_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = set(cls.__dataclass_fields__)
                return cls(**{k: v for k, v in data.items() if k in known})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        _config_path().write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get_token() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except keyring_errors.KeyringError:
        return ""


def set_token(token: str) -> None:
    if token:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except keyring_errors.KeyringError:
            pass


class StateStore:
    """Дата и результат последней синхронизации по каждому репозиторию."""

    def __init__(self, path: Path | None = None):
        self.path = path or _state_path()
        self._data: dict[str, dict] = {}
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}

    def last_sync(self, repo: str) -> datetime | None:
        value = self._data.get(repo, {}).get("last_sync")
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def last_result(self, repo: str) -> str:
        return self._data.get(repo, {}).get("last_result", "")

    def record(self, repo: str, ok: bool, message: str) -> None:
        entry = self._data.setdefault(repo, {})
        if ok:
            entry["last_sync"] = datetime.now().isoformat(timespec="seconds")
        entry["last_result"] = message
        self.save()

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
