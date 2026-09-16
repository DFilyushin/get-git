from unittest.mock import Mock

import pytest

from app.core.github_client import GitHubClient, GitHubError


def make_response(json_data, links=None, status=200, headers=None):
    response = Mock()
    response.status_code = status
    response.json.return_value = json_data
    response.links = links or {}
    response.headers = headers or {}
    response.text = ""
    return response


def repo_json(rid, full_name, **extra):
    item = {
        "id": rid,
        "name": full_name.split("/")[-1],
        "full_name": full_name,
        "ssh_url": f"git@github.com:{full_name}.git",
        "default_branch": "main",
        "archived": False,
        "permissions": {"pull": True, "push": False},
    }
    item.update(extra)
    return item


def test_list_repos_pagination_via_link_header():
    client = GitHubClient("", "token")
    client.session = Mock()
    client.session.get.side_effect = [
        make_response(
            [repo_json(1, "acme/backend")],
            links={"next": {"url": "https://api.github.com/user/repos?page=2"}},
        ),
        make_response([repo_json(2, "acme/frontend")]),
    ]

    projects = client.list_projects()

    assert [p.path_with_namespace for p in projects] == ["acme/backend", "acme/frontend"]
    assert projects[0].ssh_url_to_repo == "git@github.com:acme/backend.git"
    assert client.session.get.call_count == 2
    second_url = client.session.get.call_args_list[1].args[0]
    assert second_url == "https://api.github.com/user/repos?page=2"


def test_archived_repos_skipped():
    client = GitHubClient("https://api.github.com", "token")
    client.session = Mock()
    client.session.get.return_value = make_response(
        [repo_json(1, "acme/live"), repo_json(2, "acme/old", archived=True)]
    )

    projects = client.list_projects()

    assert [p.path_with_namespace for p in projects] == ["acme/live"]


def test_can_download_from_pull_permission():
    client = GitHubClient("https://api.github.com", "token")
    client.session = Mock()
    client.session.get.return_value = make_response(
        [repo_json(1, "acme/nopull", permissions={"pull": False})]
    )

    assert client.list_projects()[0].can_download is False


def test_enterprise_api_url():
    client = GitHubClient("https://ghe.example.com/api/v3/", "token")
    client.session = Mock()
    client.session.get.return_value = make_response([])

    client.list_projects()

    first_url = client.session.get.call_args_list[0].args[0]
    assert first_url == "https://ghe.example.com/api/v3/user/repos"


def test_invalid_token_raises():
    client = GitHubClient("", "bad")
    client.session = Mock()
    client.session.get.return_value = make_response([], status=401)

    with pytest.raises(GitHubError, match="Токен недействителен"):
        client.list_projects()


def test_rate_limit_message():
    client = GitHubClient("", "token")
    client.session = Mock()
    client.session.get.return_value = make_response(
        [], status=403, headers={"X-RateLimit-Remaining": "0"}
    )

    with pytest.raises(GitHubError, match="лимит запросов"):
        client.list_projects()
