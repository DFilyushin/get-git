"""Общий слой провайдеров (GitLab / GitHub).

Клиент любого провайдера обязан предоставлять:
- list_projects() -> list[Project]
- check_token() -> str (имя владельца токена)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.storage import Profile

PROVIDER_GITLAB = "gitlab"
PROVIDER_GITHUB = "github"
PROVIDER_TITLES = {PROVIDER_GITLAB: "GitLab", PROVIDER_GITHUB: "GitHub"}


class ProviderError(Exception):
    """Ошибка обращения к API источника (общая для всех провайдеров)."""


@dataclass
class Project:
    id: int
    name: str
    path_with_namespace: str
    ssh_url_to_repo: str
    default_branch: str
    can_download: bool = True


def make_client(profile: "Profile", token: str):
    """Клиент API по типу источника."""
    from app.core.github_client import GitHubClient
    from app.core.gitlab_client import GitLabClient

    if profile.provider == PROVIDER_GITHUB:
        return GitHubClient(profile.api_url, token)
    return GitLabClient(profile.api_url, token)
