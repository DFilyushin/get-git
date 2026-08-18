"""Git-операции через системный git.exe.

Локальные копии считаются read-only зеркалами сервера: синхронизация
принудительно приводит все локальные ветки к состоянию origin и удаляет
всё лишнее из рабочей копии.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)

GIT_TIMEOUT = 600  # секунд на одну git-команду

# Запущенные git-процессы: при выходе из приложения их нужно принудительно
# завершить, иначе рабочие потоки (и весь процесс) зависают до таймаута
_active_procs: set[subprocess.Popen] = set()
_procs_lock = threading.Lock()


class GitError(Exception):
    pass


def terminate_all() -> int:
    """Принудительно завершает все запущенные git-процессы. Возвращает их число."""
    with _procs_lock:
        procs = list(_active_procs)
    for proc in procs:
        _kill_tree(proc)
    if procs:
        log.warning("Принудительно завершено git-процессов: %d", len(procs))
    return len(procs)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Завершает процесс вместе с потомками: дочерний ssh держит пайпы git,
    и без него communicate() не разблокируется."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    try:
        proc.kill()
    except OSError:
        pass


def find_git() -> str | None:
    return shutil.which("git")


def build_env(ssh_key_path: str | None) -> dict:
    """Окружение для git: неинтерактивный ssh с явным ключом."""
    env = os.environ.copy()
    ssh_parts = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if ssh_key_path and Path(ssh_key_path).is_file():
        key = str(Path(ssh_key_path)).replace("\\", "/")
        ssh_parts += ["-i", f'"{key}"', "-o", "IdentitiesOnly=yes"]
    env["GIT_SSH_COMMAND"] = " ".join(ssh_parts)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_git(
    args: list[str],
    cwd: Path | str | None = None,
    env: dict | None = None,
    timeout: int = GIT_TIMEOUT,
) -> str:
    cmd = ["git"] + list(args)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise GitError("git не найден в PATH") from exc
    with _procs_lock:
        _active_procs.add(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(proc)
        proc.communicate()
        raise GitError(f"git {args[0]}: превышен таймаут {timeout} с") from exc
    finally:
        with _procs_lock:
            _active_procs.discard(proc)
    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip() or "процесс прерван"
        raise GitError(f"git {args[0]}: {detail[-1000:]}")
    return stdout


def clone_repo(ssh_url: str, dest: Path, ssh_key_path: str | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git(
        ["clone", "-c", "core.longpaths=true", "--origin", "origin", ssh_url, str(dest)],
        env=build_env(ssh_key_path),
    )


def sync_repo(dest: Path, default_branch: str, ssh_key_path: str | None) -> str:
    """Полная синхронизация локальной копии с origin.

    Возвращает имя ветки, оставшейся checked-out.
    """
    env = build_env(ssh_key_path)
    run_git(
        ["fetch", "origin", "--prune", "--prune-tags", "--tags", "--force"],
        cwd=dest,
        env=env,
    )

    remote_branches = _branches(dest, "refs/remotes/origin", strip=3) - {"HEAD"}
    if not remote_branches:
        raise GitError("на сервере нет ни одной ветки")

    current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest, env=env).strip()
    if current == "HEAD" or current not in remote_branches:
        # detached HEAD либо текущая ветка удалена на сервере
        target = default_branch if default_branch in remote_branches else sorted(remote_branches)[0]
        run_git(["checkout", "--force", "-B", target, f"origin/{target}"], cwd=dest, env=env)
        current = target

    for branch in sorted(remote_branches):
        if branch == current:
            run_git(["reset", "--hard", f"origin/{branch}"], cwd=dest, env=env)
        else:
            run_git(["branch", "--force", branch, f"origin/{branch}"], cwd=dest, env=env)

    for branch in sorted(_branches(dest, "refs/heads", strip=2) - remote_branches):
        if branch != current:
            run_git(["branch", "-D", branch], cwd=dest, env=env)

    run_git(["clean", "-fd"], cwd=dest, env=env)
    return current


def _branches(dest: Path, ref_prefix: str, strip: int) -> set[str]:
    out = run_git(["for-each-ref", ref_prefix, f"--format=%(refname:strip={strip})"], cwd=dest)
    return {line.strip() for line in out.splitlines() if line.strip()}
