"""Служебные пути и хранение токенов.

Настройки приложения хранятся в SQLite-базе %APPDATA%\\GetGit\\getgit.db
(см. app.core.storage). Здесь — каталог данных приложения и токены
источников: по одной записи Диспетчера учётных данных Windows (keyring)
на каждый источник.
"""
from __future__ import annotations

import os
from pathlib import Path

import keyring
from keyring import errors as keyring_errors

APP_NAME = "GetGit"
KEYRING_SERVICE = "GetGit"
# Записи формата v1 (до мультиисточников) — нужны только для миграции
LEGACY_KEYRING_SERVICE = "GetGit-GitLab"
LEGACY_KEYRING_USER = "token"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    directory = Path(base) / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _keyring_user(profile_id: str) -> str:
    return f"profile-{profile_id}"


def get_profile_token(profile_id: str) -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, _keyring_user(profile_id)) or ""
    except keyring_errors.KeyringError:
        return ""


def set_profile_token(profile_id: str, token: str) -> None:
    if token:
        keyring.set_password(KEYRING_SERVICE, _keyring_user(profile_id), token)
    else:
        delete_profile_token(profile_id)


def delete_profile_token(profile_id: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, _keyring_user(profile_id))
    except keyring_errors.KeyringError:
        pass


def get_legacy_token() -> str:
    """Токен из записи формата v1 — используется при миграции настроек."""
    try:
        return keyring.get_password(LEGACY_KEYRING_SERVICE, LEGACY_KEYRING_USER) or ""
    except keyring_errors.KeyringError:
        return ""
