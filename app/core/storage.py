"""Хранилище настроек и состояния: SQLite-база %APPDATA%\\GetGit\\getgit.db.

Схема:
- profiles   — источники (серверы GitLab/GitHub), у каждого свои настройки:
               директория хранения, SSH-ключ, число параллельных операций;
- settings   — глобальные настройки (ключ/значение);
- sync_state — дата и результат последней синхронизации по каждому
               репозиторию каждого источника.

Токены источников в базе НЕ хранятся — они в Диспетчере учётных данных
Windows (см. app.core.config).

При первом запуске v2 настройки автоматически переносятся из старых
config.json / state.json (см. migrate_legacy).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core import config as config_mod
from app.core.config import app_data_dir
from app.core.provider import PROVIDER_GITLAB

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT 'gitlab',
    api_url       TEXT NOT NULL DEFAULT '',
    base_dir      TEXT NOT NULL DEFAULT '',
    ssh_key_path  TEXT NOT NULL DEFAULT '',
    parallel_jobs INTEGER NOT NULL DEFAULT 4,
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sync_state (
    profile_id  TEXT NOT NULL,
    repo        TEXT NOT NULL,
    last_sync   TEXT,
    last_result TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (profile_id, repo)
);
"""


def _default_ssh_key() -> str:
    return str(Path.home() / ".ssh" / "id_ed25519")


@dataclass
class Profile:
    """Источник репозиториев со своими настройками."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    provider: str = PROVIDER_GITLAB
    api_url: str = ""
    base_dir: str = ""
    ssh_key_path: str = field(default_factory=_default_ssh_key)
    parallel_jobs: int = 4


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or app_data_dir() / "getgit.db"
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------- источники ----------

    def profiles(self) -> list[Profile]:
        rows = self._conn.execute(
            "SELECT * FROM profiles ORDER BY rowid"  # порядок добавления
        ).fetchall()
        return [self._to_profile(row) for row in rows]

    def get_profile(self, profile_id: str) -> Profile | None:
        row = self._conn.execute(
            "SELECT * FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        return self._to_profile(row) if row else None

    def save_profile(self, profile: Profile) -> None:
        self._conn.execute(
            """
            INSERT INTO profiles (id, name, provider, api_url, base_dir,
                                  ssh_key_path, parallel_jobs, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                provider = excluded.provider,
                api_url = excluded.api_url,
                base_dir = excluded.base_dir,
                ssh_key_path = excluded.ssh_key_path,
                parallel_jobs = excluded.parallel_jobs
            """,
            (
                profile.id,
                profile.name,
                profile.provider,
                profile.api_url,
                profile.base_dir,
                profile.ssh_key_path,
                profile.parallel_jobs,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()

    def delete_profile(self, profile_id: str) -> None:
        self._conn.execute("DELETE FROM sync_state WHERE profile_id = ?", (profile_id,))
        self._conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        self._conn.commit()

    @staticmethod
    def _to_profile(row: sqlite3.Row) -> Profile:
        return Profile(
            id=row["id"],
            name=row["name"],
            provider=row["provider"],
            api_url=row["api_url"],
            base_dir=row["base_dir"],
            ssh_key_path=row["ssh_key_path"],
            parallel_jobs=row["parallel_jobs"],
        )

    # ---------- глобальные настройки ----------

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    # ---------- состояние синхронизации ----------

    def record_sync(self, profile_id: str, repo: str, ok: bool, message: str) -> None:
        now = datetime.now().isoformat(timespec="seconds") if ok else None
        self._conn.execute(
            """
            INSERT INTO sync_state (profile_id, repo, last_sync, last_result)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id, repo) DO UPDATE SET
                last_sync = COALESCE(excluded.last_sync, sync_state.last_sync),
                last_result = excluded.last_result
            """,
            (profile_id, repo, now, message),
        )
        self._conn.commit()

    def last_sync(self, profile_id: str, repo: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_sync FROM sync_state WHERE profile_id = ? AND repo = ?",
            (profile_id, repo),
        ).fetchone()
        if not row or not row["last_sync"]:
            return None
        try:
            return datetime.fromisoformat(row["last_sync"])
        except ValueError:
            return None

    def last_result(self, profile_id: str, repo: str) -> str:
        row = self._conn.execute(
            "SELECT last_result FROM sync_state WHERE profile_id = ? AND repo = ?",
            (profile_id, repo),
        ).fetchone()
        return row["last_result"] if row else ""


class SyncState:
    """Состояние синхронизации одного источника (обёртка над Database)."""

    def __init__(self, db: Database, profile_id: str):
        self._db = db
        self._profile_id = profile_id

    def last_sync(self, repo: str) -> datetime | None:
        return self._db.last_sync(self._profile_id, repo)

    def last_result(self, repo: str) -> str:
        return self._db.last_result(self._profile_id, repo)

    def record(self, repo: str, ok: bool, message: str) -> None:
        self._db.record_sync(self._profile_id, repo, ok, message)


def migrate_legacy(
    db: Database,
    config_path: Path | None = None,
    state_path: Path | None = None,
    legacy_token_reader=None,
    token_writer=None,
) -> Profile | None:
    """Однократный перенос настроек v1 (config.json/state.json) в базу.

    Возвращает созданный профиль либо None, если переносить нечего.
    Старые файлы переименовываются в *.bak, токен копируется в запись
    нового профиля (старая запись keyring не удаляется).
    """
    if db.profiles():
        return None
    config_path = config_path or app_data_dir() / "config.json"
    if not config_path.is_file():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    profile = Profile(
        name="GitLab",
        provider=PROVIDER_GITLAB,
        api_url=data.get("gitlab_url", "") or "",
        base_dir=data.get("base_dir", "") or "",
        ssh_key_path=data.get("ssh_key_path") or _default_ssh_key(),
        parallel_jobs=int(data.get("parallel_jobs") or 4),
    )
    db.save_profile(profile)
    db.set_setting("active_profile", profile.id)
    db.set_setting("show_unavailable", "1" if data.get("show_unavailable", True) else "0")

    state_path = state_path or app_data_dir() / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for repo, entry in state.items():
                db._conn.execute(
                    "INSERT OR REPLACE INTO sync_state "
                    "(profile_id, repo, last_sync, last_result) VALUES (?, ?, ?, ?)",
                    (
                        profile.id,
                        repo,
                        entry.get("last_sync"),
                        entry.get("last_result", ""),
                    ),
                )
            db._conn.commit()
        except (json.JSONDecodeError, OSError):
            pass

    read_token = legacy_token_reader or config_mod.get_legacy_token
    write_token = token_writer or config_mod.set_profile_token
    try:
        token = read_token()
        if token:
            write_token(profile.id, token)
    except Exception:  # noqa: BLE001 — миграция не должна падать из-за keyring
        log.exception("Не удалось перенести токен из старой записи keyring")

    for old in (config_path, state_path):
        try:
            if old.is_file():
                old.rename(old.with_suffix(old.suffix + ".bak"))
        except OSError:
            pass

    log.info("Настройки перенесены из %s в %s", config_path.name, db.path.name)
    return profile
