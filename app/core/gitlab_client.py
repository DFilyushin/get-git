"""Клиент REST API корпоративного GitLab (v4)."""
from __future__ import annotations

from dataclasses import dataclass

import requests


class GitLabError(Exception):
    pass


# Скачивание кода приватного проекта требует роли Reporter (30 — Developer, 20 — Reporter)
DOWNLOAD_ACCESS_LEVEL = 20


@dataclass
class Project:
    id: int
    name: str
    path_with_namespace: str
    ssh_url_to_repo: str
    default_branch: str
    can_download: bool = True


class GitLabClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["PRIVATE-TOKEN"] = token

    def check_token(self) -> str:
        """Возвращает имя пользователя, которому принадлежит токен."""
        return self._get("/api/v4/user").json().get("username", "")

    def list_projects(self) -> list[Project]:
        """Все не-архивные проекты, где пользователь является участником."""
        projects: list[Project] = []
        page = "1"
        while page:
            response = self._get(
                "/api/v4/projects",
                params={
                    "membership": "true",
                    "archived": "false",
                    "per_page": "100",
                    "page": page,
                    "order_by": "path",
                    "sort": "asc",
                },
            )
            for item in response.json():
                projects.append(
                    Project(
                        id=item["id"],
                        name=item.get("name", ""),
                        path_with_namespace=item["path_with_namespace"],
                        ssh_url_to_repo=item["ssh_url_to_repo"],
                        default_branch=item.get("default_branch") or "main",
                        can_download=_can_download(item),
                    )
                )
            page = response.headers.get("X-Next-Page", "")
        return projects

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        try:
            response = self.session.get(
                self.base_url + path, params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise GitLabError(f"GitLab недоступен: {exc}") from exc
        if response.status_code in (401, 403):
            raise GitLabError(
                "Токен недействителен или не имеет права read_api — проверьте «Настройки…»"
            )
        if response.status_code >= 400:
            raise GitLabError(
                f"GitLab вернул ошибку {response.status_code}: {response.text[:200]}"
            )
        return response


def _can_download(item: dict) -> bool:
    """Можно ли скачать код проекта: public/internal — да, private — от роли Reporter."""
    if item.get("visibility") in ("public", "internal"):
        return True
    permissions = item.get("permissions")
    if not permissions:
        # API не вернул права — не ограничиваем, ошибка всплывёт при клонировании
        return True
    level = 0
    for key in ("project_access", "group_access"):
        access = permissions.get(key) or {}
        level = max(level, access.get("access_level") or 0)
    return level >= DOWNLOAD_ACCESS_LEVEL
