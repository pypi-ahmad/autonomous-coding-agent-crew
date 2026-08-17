from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

from agent_crew.policy import get_policy
from agent_crew.workspace import _sandbox_env, run_subprocess, safe_file

UNSAFE = set(";|&`$<>\n")
PIP_DENY = {"-r", "--requirement", "--target", "--prefix", "--editable", "-e"}


def _refuse(arg: str) -> None:
    if any(char in arg for char in UNSAFE):
        raise ValueError(f"Refused unsafe argument: {arg}")


def build_command(workspace: Path, command: str) -> list[str]:
    parts = shlex.split(command, posix=False)
    if not parts:
        raise ValueError("Empty command")
    for part in parts:
        _refuse(part)
    head = parts[0].lower().removesuffix(".exe")
    rest = parts[1:]
    if head in {"rm", "del", "curl", "wget", "ssh", "powershell", "cmd", "format"}:
        raise ValueError(f"Refused command: {head}")
    if head in {"python", "python3", "py"}:
        return _python_command(workspace, rest)
    if head == "pip":
        return _pip_command(workspace, rest)
    if head == "git" and rest and rest[0] in {"status", "diff", "log", "branch"}:
        git = shutil.which("git")
        if not git:
            raise ValueError("git not found")
        return [git, *rest]
    if head == "pytest":
        return [sys.executable, "-m", "pytest", *rest]
    if head == "node":
        return _node_command(workspace, rest)
    raise ValueError(f"Command not allowlisted: {head}")


def _node_command(workspace: Path, rest: list[str]) -> list[str]:
    node = shutil.which("node")
    if not node:
        raise ValueError("node not found")
    if rest and rest[0] == "--test":
        for part in rest[1:]:
            if part.endswith((".js", ".ts", ".mjs", ".cjs")):
                safe_file(workspace, part)
        return [node, *rest]
    if len(rest) == 1 and rest[0].endswith(".js"):
        safe_file(workspace, rest[0])
        return [node, rest[0]]
    raise ValueError("node is limited to a .js file or --test")


def _python_command(workspace: Path, rest: list[str]) -> list[str]:
    if rest[:2] == ["-m", "pytest"]:
        return [sys.executable, *rest]
    if rest[:2] == ["-m", "pip"]:
        return _pip_command(workspace, rest[2:])
    if rest[:3] == ["-m", "ruff", "check"]:
        return [sys.executable, *rest]
    if rest[:3] == ["-m", "ty", "check"]:
        return [sys.executable, *rest]
    if len(rest) == 1 and rest[0].endswith(".py"):
        safe_file(workspace, rest[0])
        return [sys.executable, rest[0]]
    raise ValueError("python is limited to a .py file, -m pytest, or -m pip install")


def _pip_command(workspace: Path, rest: list[str]) -> list[str]:
    if not rest or rest[0] != "install":
        raise ValueError("pip only supports install")
    pkgs = rest[1:]
    if any(flag in pkgs for flag in PIP_DENY):
        raise ValueError("pip flags are limited to package names")
    if not pkgs:
        raise ValueError("pip install needs a package")
    vendor = workspace / ".vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    return [sys.executable, "-m", "pip", "install", "--target", str(vendor), *pkgs]


def run_terminal(workspace: Path, command: str) -> tuple[bool, str]:
    policy = get_policy()
    argv = build_command(workspace, command)
    if "-m" in argv and "pip" in argv and not policy.allow_pip:
        raise ValueError("pip disabled by policy")
    if not policy.allow_terminal:
        raise ValueError("Terminal disabled by policy")
    if policy.dry_run:
        return True, "dry-run: " + " ".join(argv)
    return run_subprocess(argv, cwd=workspace, timeout=120, env=_sandbox_env(workspace))
