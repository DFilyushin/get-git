"""Интеграционные тесты git-операций на локальных репозиториях (без сети)."""
import subprocess
from pathlib import Path

import pytest

from app.core import git_ops

IDENT = ["-c", "user.email=test@test", "-c", "user.name=test"]


def run(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True, capture_output=True)


def commit_file(repo: Path, name: str, content: str, message: str):
    (repo / name).write_text(content, encoding="utf-8")
    run(["add", "."], repo)
    run(IDENT + ["commit", "-m", message], repo)


def head_of(repo: Path, branch: str) -> str:
    out = subprocess.run(
        ["git", "rev-parse", branch], cwd=str(repo), check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    repo.mkdir()
    run(["init", "-b", "main"], repo)
    commit_file(repo, "a.txt", "v1", "c1")
    return repo


@pytest.fixture
def clone(origin: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "mirror" / "group" / "repo"
    git_ops.clone_repo(str(origin), dest, ssh_key_path=None)
    return dest


def test_clone_creates_repo(clone: Path):
    assert (clone / ".git").is_dir()
    assert (clone / "a.txt").read_text(encoding="utf-8") == "v1"


def test_sync_pulls_new_commits_and_branches(origin: Path, clone: Path):
    commit_file(origin, "a.txt", "v2", "c2")
    run(["checkout", "-b", "feature/x"], origin)
    commit_file(origin, "b.txt", "f1", "f1")
    run(["checkout", "main"], origin)

    current = git_ops.sync_repo(clone, "main", ssh_key_path=None)

    assert current == "main"
    assert (clone / "a.txt").read_text(encoding="utf-8") == "v2"
    assert head_of(clone, "feature/x") == head_of(origin, "feature/x")


def test_sync_deletes_removed_branches(origin: Path, clone: Path):
    run(["checkout", "-b", "old"], origin)
    commit_file(origin, "c.txt", "x", "old")
    run(["checkout", "main"], origin)
    git_ops.sync_repo(clone, "main", ssh_key_path=None)
    assert head_of(clone, "old")

    run(["branch", "-D", "old"], origin)
    git_ops.sync_repo(clone, "main", ssh_key_path=None)

    branches = subprocess.run(
        ["git", "branch", "--list", "old"],
        cwd=str(clone), check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert branches == ""


def test_sync_discards_local_changes_and_untracked(origin: Path, clone: Path):
    (clone / "a.txt").write_text("испорчено", encoding="utf-8")
    (clone / "junk.tmp").write_text("junk", encoding="utf-8")

    git_ops.sync_repo(clone, "main", ssh_key_path=None)

    assert (clone / "a.txt").read_text(encoding="utf-8") == "v1"
    assert not (clone / "junk.tmp").exists()


def test_sync_recovers_when_current_branch_deleted(origin: Path, clone: Path):
    run(["checkout", "-b", "temp"], origin)
    commit_file(origin, "t.txt", "t", "t")
    run(["checkout", "main"], origin)
    git_ops.sync_repo(clone, "main", ssh_key_path=None)
    run(["checkout", "temp"], clone)

    run(["branch", "-D", "temp"], origin)
    current = git_ops.sync_repo(clone, "main", ssh_key_path=None)

    assert current == "main"
    assert not (clone / "t.txt").exists()


def test_sync_error_on_missing_remote(tmp_path: Path):
    repo = tmp_path / "lonely"
    repo.mkdir()
    run(["init", "-b", "main"], repo)

    with pytest.raises(git_ops.GitError):
        git_ops.sync_repo(repo, "main", ssh_key_path=None)
