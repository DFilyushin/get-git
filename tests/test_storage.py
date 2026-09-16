import json
from pathlib import Path

import pytest

from app.core.provider import PROVIDER_GITHUB, PROVIDER_GITLAB
from app.core.storage import Database, Profile, SyncState, migrate_legacy


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "getgit.db")
    yield database
    database.close()


def test_profile_crud(db: Database):
    profile = Profile(
        name="Рабочий GitLab",
        provider=PROVIDER_GITLAB,
        api_url="https://gitlab.example.com",
        base_dir=r"D:\repos\gitlab",
        parallel_jobs=8,
    )
    db.save_profile(profile)
    github = Profile(name="GitHub", provider=PROVIDER_GITHUB, api_url="https://api.github.com")
    db.save_profile(github)

    assert {p.name for p in db.profiles()} == {"Рабочий GitLab", "GitHub"}
    loaded = db.get_profile(profile.id)
    assert loaded.parallel_jobs == 8
    assert loaded.base_dir == r"D:\repos\gitlab"

    profile.base_dir = r"E:\mirror"
    db.save_profile(profile)
    assert db.get_profile(profile.id).base_dir == r"E:\mirror"
    assert len(db.profiles()) == 2  # обновление, а не дубль

    db.delete_profile(profile.id)
    assert db.get_profile(profile.id) is None
    assert len(db.profiles()) == 1


def test_settings_kv(db: Database):
    assert db.get_setting("show_unavailable", "1") == "1"
    db.set_setting("show_unavailable", "0")
    assert db.get_setting("show_unavailable", "1") == "0"
    db.set_setting("show_unavailable", "1")
    assert db.get_setting("show_unavailable") == "1"


def test_sync_state_per_profile(db: Database):
    a = Profile(name="A")
    b = Profile(name="B")
    db.save_profile(a)
    db.save_profile(b)

    state_a = SyncState(db, a.id)
    state_b = SyncState(db, b.id)
    state_a.record("group/repo", True, "обновлён")
    state_b.record("group/repo", False, "ошибка: сеть")

    assert state_a.last_sync("group/repo") is not None
    assert state_a.last_result("group/repo") == "обновлён"
    assert state_b.last_sync("group/repo") is None  # ошибка не двигает дату
    assert state_b.last_result("group/repo") == "ошибка: сеть"

    # ошибка после успеха: дата последнего успеха сохраняется
    state_a.record("group/repo", False, "ошибка: занят файл")
    assert state_a.last_sync("group/repo") is not None
    assert state_a.last_result("group/repo") == "ошибка: занят файл"

    db.delete_profile(a.id)
    assert db.last_result(a.id, "group/repo") == ""


def test_migrate_legacy(db: Database, tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "base_dir": r"D:\repos",
                "gitlab_url": "https://gitlab.example.com",
                "ssh_key_path": r"C:\keys\id_ed25519",
                "parallel_jobs": 6,
                "show_unavailable": False,
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {"dev/backend": {"last_sync": "2026-08-18T12:00:00", "last_result": "обновлён"}}
        ),
        encoding="utf-8",
    )
    saved_tokens = {}

    profile = migrate_legacy(
        db,
        config_path=config_path,
        state_path=state_path,
        legacy_token_reader=lambda: "old-token",
        token_writer=lambda pid, token: saved_tokens.update({pid: token}),
    )

    assert profile is not None
    assert saved_tokens == {profile.id: "old-token"}
    assert profile.provider == PROVIDER_GITLAB
    assert profile.api_url == "https://gitlab.example.com"
    assert profile.base_dir == r"D:\repos"
    assert profile.parallel_jobs == 6
    assert db.get_setting("active_profile") == profile.id
    assert db.get_setting("show_unavailable") == "0"
    assert db.last_result(profile.id, "dev/backend") == "обновлён"
    assert db.last_sync(profile.id, "dev/backend") is not None
    assert not config_path.exists() and config_path.with_suffix(".json.bak").exists()
    assert not state_path.exists()

    # повторная миграция не создаёт дублей
    assert migrate_legacy(db, config_path=config_path, state_path=state_path) is None
    assert len(db.profiles()) == 1


def test_migrate_legacy_nothing_to_do(db: Database, tmp_path: Path):
    assert migrate_legacy(db, config_path=tmp_path / "no.json", state_path=tmp_path / "no2.json") is None
    assert db.profiles() == []
