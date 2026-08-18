from unittest.mock import Mock

import pytest

from app.core.gitlab_client import GitLabClient, GitLabError


def make_response(json_data, headers=None, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = json_data
    response.headers = headers or {}
    response.text = ""
    return response


def project_json(pid, path):
    return {
        "id": pid,
        "name": path.split("/")[-1],
        "path_with_namespace": path,
        "ssh_url_to_repo": f"git@gitlab.example.com:{path}.git",
        "default_branch": "main",
    }


def test_list_projects_pagination():
    client = GitLabClient("https://gitlab.example.com/", "token")
    client.session = Mock()
    client.session.get.side_effect = [
        make_response([project_json(1, "dev/backend")], {"X-Next-Page": "2"}),
        make_response([project_json(2, "ops/infra")], {"X-Next-Page": ""}),
    ]

    projects = client.list_projects()

    assert [p.path_with_namespace for p in projects] == ["dev/backend", "ops/infra"]
    assert projects[0].ssh_url_to_repo == "git@gitlab.example.com:dev/backend.git"
    assert client.session.get.call_count == 2
    first_url = client.session.get.call_args_list[0].args[0]
    assert first_url == "https://gitlab.example.com/api/v4/projects"


def test_default_branch_fallback():
    client = GitLabClient("https://gitlab.example.com", "token")
    client.session = Mock()
    item = project_json(1, "dev/empty")
    item["default_branch"] = None
    client.session.get.return_value = make_response([item], {})

    assert client.list_projects()[0].default_branch == "main"


def test_can_download_private_guest_denied():
    client = GitLabClient("https://gitlab.example.com", "token")
    client.session = Mock()
    item = project_json(1, "dev/secret")
    item["visibility"] = "private"
    item["permissions"] = {"project_access": {"access_level": 10}, "group_access": None}
    client.session.get.return_value = make_response([item], {})

    assert client.list_projects()[0].can_download is False


def test_can_download_private_reporter_allowed():
    client = GitLabClient("https://gitlab.example.com", "token")
    client.session = Mock()
    item = project_json(1, "dev/backend")
    item["visibility"] = "private"
    item["permissions"] = {"project_access": None, "group_access": {"access_level": 20}}
    client.session.get.return_value = make_response([item], {})

    assert client.list_projects()[0].can_download is True


def test_can_download_internal_guest_allowed():
    client = GitLabClient("https://gitlab.example.com", "token")
    client.session = Mock()
    item = project_json(1, "dev/wiki")
    item["visibility"] = "internal"
    item["permissions"] = {"project_access": {"access_level": 10}, "group_access": None}
    client.session.get.return_value = make_response([item], {})

    assert client.list_projects()[0].can_download is True


def test_can_download_without_permissions_defaults_true():
    client = GitLabClient("https://gitlab.example.com", "token")
    client.session = Mock()
    client.session.get.return_value = make_response([project_json(1, "dev/x")], {})

    assert client.list_projects()[0].can_download is True


def test_invalid_token_raises():
    client = GitLabClient("https://gitlab.example.com", "bad")
    client.session = Mock()
    client.session.get.return_value = make_response([], status=401)

    with pytest.raises(GitLabError, match="read_api"):
        client.list_projects()
