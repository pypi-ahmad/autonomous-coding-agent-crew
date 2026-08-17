from __future__ import annotations

from pathlib import Path

from crewai.tools import BaseTool
from pydantic import Field

from agent_crew.codeintel import analyze_project, rename_symbol, search_code, search_semantic
from agent_crew.quality import evaluate_quality
from agent_crew.shell import run_terminal
from agent_crew.stack import detect_stack, format_stack, practices_for
from agent_crew.workspace import (
    append_terminal_log,
    create_file,
    list_files,
    read_file,
    run_python,
    write_file,
)


class _WsTool(BaseTool):
    workspace: str = Field(description="Absolute workspace path")
    protect_tests: bool = Field(default=False)


class ListFilesTool(_WsTool):
    name: str = "list_files"
    description: str = "List every file in the workspace (relative paths)."

    def _run(self) -> str:
        names = list_files(Path(self.workspace))
        return "\n".join(names) if names else "(empty workspace)"


class ReadFileTool(_WsTool):
    name: str = "read_file"
    description: str = "Read a file relative to the workspace."

    def _run(self, path: str) -> str:
        return read_file(Path(self.workspace), path)


class WriteFileTool(_WsTool):
    name: str = "write_file"
    description: str = "Create or overwrite a file relative to the workspace."

    def _run(self, path: str, content: str) -> str:
        written = write_file(Path(self.workspace), path, content, protect_tests=self.protect_tests)
        return f"Wrote {written}"


class CreateFileTool(_WsTool):
    name: str = "create_file"
    description: str = "Create a new file. Fails if the path already exists."

    def _run(self, path: str, content: str) -> str:
        written = create_file(Path(self.workspace), path, content, protect_tests=self.protect_tests)
        return f"Created {written}"


class RunPythonTool(_WsTool):
    name: str = "run_python"
    description: str = "Run a .py file in the workspace sandbox (cwd jail, stripped env, timeout)."

    def _run(self, path: str) -> str:
        ok, output = run_python(Path(self.workspace), path)
        status = "ok" if ok else "failed"
        return f"{status}\n{output}"


class SearchCodeTool(_WsTool):
    name: str = "search_code"
    description: str = "Keyword/regex search across project text files."

    def _run(self, pattern: str) -> str:
        return search_code(Path(self.workspace), pattern)


class SearchSemanticTool(_WsTool):
    name: str = "search_semantic"
    description: str = "Token-overlap search over Python identifiers (no remote embeddings)."

    def _run(self, query: str) -> str:
        return search_semantic(Path(self.workspace), query)


class RenameSymbolTool(_WsTool):
    name: str = "rename_symbol"
    description: str = "Rename an identifier across .py/.js/.ts files in the workspace."

    def _run(self, old: str, new: str) -> str:
        return rename_symbol(Path(self.workspace), old, new)


class AnalyzeProjectTool(_WsTool):
    name: str = "analyze_project"
    description: str = "Summarize stack, functions, classes, and imports in the workspace."

    def _run(self) -> str:
        return analyze_project(Path(self.workspace))


class RunTerminalTool(_WsTool):
    name: str = "run_terminal"
    description: str = (
        "Run an allowlisted command: python <file.py>, pytest, pip install <pkg>, "
        "node <file.js>, node --test, python -m ruff check, python -m ty check, "
        "git status|diff|log|branch. No shell metacharacters."
    )

    def _run(self, command: str) -> str:
        ok, output = run_terminal(Path(self.workspace), command)
        append_terminal_log(Path(self.workspace), command, ok=ok, output=output)
        status = "ok" if ok else "failed"
        return f"{status}\n{output}"


class DetectStackTool(_WsTool):
    name: str = "detect_stack"
    description: str = "Detect language, framework, database, and fullstack from the workspace."

    def _run(self) -> str:
        stack = detect_stack(Path(self.workspace))
        practices = practices_for(stack)
        extra = f"\n{practices}" if practices else ""
        return format_stack(stack) + extra


class RunQualityTool(_WsTool):
    name: str = "run_quality"
    description: str = (
        "Run quality gates: test levels, coverage floor, ruff, ty, security scan, perf probe."
    )

    def _run(self) -> str:
        return evaluate_quality(
            Path(self.workspace),
            tests_ok=True,
            coverage=-1.0,
        ).report


def make_fs_tools(workspace: Path, *, protect_tests: bool = False) -> list[BaseTool]:
    root = str(workspace.resolve())
    return [
        ListFilesTool(workspace=root, protect_tests=protect_tests),
        ReadFileTool(workspace=root, protect_tests=protect_tests),
        WriteFileTool(workspace=root, protect_tests=protect_tests),
        CreateFileTool(workspace=root, protect_tests=protect_tests),
        RunPythonTool(workspace=root, protect_tests=protect_tests),
        SearchCodeTool(workspace=root, protect_tests=protect_tests),
        SearchSemanticTool(workspace=root, protect_tests=protect_tests),
        RenameSymbolTool(workspace=root, protect_tests=protect_tests),
        AnalyzeProjectTool(workspace=root, protect_tests=protect_tests),
        DetectStackTool(workspace=root, protect_tests=protect_tests),
        RunQualityTool(workspace=root, protect_tests=protect_tests),
        RunTerminalTool(workspace=root, protect_tests=protect_tests),
    ]


READ_TOOL_NAMES = {
    "list_files",
    "read_file",
    "search_code",
    "search_semantic",
    "analyze_project",
    "detect_stack",
    "run_quality",
}


def make_read_tools(workspace: Path, *, protect_tests: bool = False) -> list[BaseTool]:
    return [
        tool
        for tool in make_fs_tools(workspace, protect_tests=protect_tests)
        if tool.name in READ_TOOL_NAMES
    ]
