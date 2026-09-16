"""Клиент REST API GitHub (github.com и GitHub Enterprise Server)."""
from __future__ import annotations

import requests

from app.core.provider import Project, ProviderError

DEFAULT_API_URL = "https://api.github.com"


class GitHubError(ProviderError):
    pass


class GitHubClient:
    def __init__(self, api_url: str, token: str, timeout: int = 30):
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def check_token(self) -> str:
        """Возвращает логин пользователя, которому принадлежит токен."""
        return self._get(f"{self.api_url}/user").json().get("login", "")

    def list_projects(self) -> list[Project]:
        """Все не-архивные репозитории, доступные пользователю токена."""
        projects: list[Project] = []
        url = f"{self.api_url}/user/repos"
        params: dict | None = {
            "per_page": "100",
            "affiliation": "owner,collaborator,organization_member",
            "sort": "full_name",
        }
        while url:
            response = self._get(url, params=params)
            params = None  # у ссылки rel="next" параметры уже включены в URL
            for item in response.json():
                if item.get("archived"):
                    continue
                permissions = item.get("permissions") or {}
                projects.append(
                    Project(
                        id=item["id"],
                        name=item.get("name", ""),
                        path_with_namespace=item["full_name"],
                        ssh_url_to_repo=item["ssh_url"],
                        default_branch=item.get("default_branch") or "main",
                        can_download=bool(permissions.get("pull", True)),
                    )
                )
            url = response.links.get("next", {}).get("url", "")
        return projects

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GitHubError(f"GitHub недоступен: {exc}") from exc
        if response.status_code == 401:
            raise GitHubError("Токен недействителен — проверьте настройки источника")
        if response.status_code == 403:
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raise GitHubError("Исчерпан лимит запросов GitHub API — повторите позже")
            raise GitHubError(
                "Нет доступа (403) — проверьте права токена (scope repo или "
                "Contents: Read) и авторизацию SSO для организации"
            )
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub вернул ошибку {response.status_code}: {response.text[:200]}"
            )
        return response
