"""Index-first hooks: a SessionStart note and a PreToolUse guard (hooks.py)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from codebase_index import hooks, scaffold


@pytest.fixture(autouse=True)
def _state_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CBX_HOOK_STATE", str(tmp_path / "hook-state"))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    db = tmp_path / "repo" / hooks.INDEX_REL
    db.parent.mkdir(parents=True)
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO files VALUES (?)", [(i,) for i in range(3)])
    conn.commit()
    conn.close()
    return tmp_path / "repo"


def _call(root: Path, tool: str, session: str = "s1", **tool_input):
    return hooks.guard({"session_id": session, "cwd": str(root / "src"),
                        "tool_name": tool, "tool_input": tool_input})


def _denied(reply) -> bool:
    return bool(reply) and reply["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_session_start_notes_the_index_only_where_one_exists(repo: Path, tmp_path: Path):
    reply = hooks.session_start({"cwd": str(repo)})
    context = reply["hookSpecificOutput"]["additionalContext"]
    assert "(3 files)" in context and "--compact" in context
    assert hooks.session_start({"cwd": str(tmp_path)}) is None


def test_first_code_search_is_sent_to_the_index_and_its_retry_runs(repo: Path):
    first = _call(repo, "Grep", pattern="TownService.refresh")
    assert _denied(first)
    reason = first["hookSpecificOutput"]["permissionDecisionReason"]
    assert 'codebase-index search "TownService.refresh" --compact' in reason
    assert _call(repo, "Grep", pattern="TownService.refresh") is None   # the retry
    assert _denied(_call(repo, "Grep", pattern="somethingElse"))          # a new search


def test_using_the_index_turns_the_guard_off_for_the_session(repo: Path):
    assert _call(repo, "Bash", command="cd x && codebase-index refs A.b --compact") is None
    assert _call(repo, "Grep", pattern="anything") is None
    assert _call(repo, "Bash", command="rg -n foo src") is None
    assert _denied(_call(repo, "Grep", session="other", pattern="anything"))


@pytest.mark.parametrize("command", [
    "grep -rn TODO docs/*.md",
    "ps aux | grep java",
    "git log --oneline | grep fix",
    "ls -la",
    "rg -n error build.log",
])
def test_non_code_and_non_search_shell_commands_pass(repo: Path, command: str):
    assert _call(repo, "Bash", command=command) is None


def test_the_retry_is_matched_by_search_term_not_by_the_whole_call(repo: Path):
    assert _denied(_call(repo, "Bash", command="grep -rn TownService src",
                         description="Find the service"))
    assert _call(repo, "Bash", command="cd src && grep -rn TownService . | head",
                 description="Find it again") is None


def test_an_index_command_that_builds_the_index_turns_the_guard_off(tmp_path: Path, repo: Path):
    # The first `codebase-index search` in a fresh repository builds the index, so the
    # guard sees that call before any index exists.
    fresh = tmp_path / "fresh"
    (fresh / "src").mkdir(parents=True)
    assert _call(fresh, "Bash", command='codebase-index search "x" --compact') is None
    assert _call(repo, "Grep", pattern="anything") is None


@pytest.mark.parametrize("command", [
    # A heredoc body is file content, not commands.
    "cat > /tmp/close.ps1 <<'EOF'\n$log = Get-Content x; Select-String \"BUILD FAILED\" $log\nEOF\n"
    "echo done",
    "python - <<EOF\nimport re; grep = 1\nEOF",
])
def test_heredoc_bodies_are_not_searched(repo: Path, command: str):
    assert _call(repo, "Bash", command=command) is None


def test_a_search_on_its_own_line_is_guarded_and_quoted_alternation_kept(repo: Path):
    reply = _call(repo, "Bash", command='ls src\ngrep -rn "Lifecycle\\|onInit" src --include=*.java')
    assert _denied(reply)
    assert 'search "Lifecycle onInit"' in reply["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "grep -rn treasurerDeparted --include=*.java .",
    "cd /c/Projects/x && rg -n 'TownService.refresh' realism-polity",
    "git grep -n place",
])
def test_code_searches_in_the_shell_are_guarded(repo: Path, command: str):
    assert _denied(_call(repo, "Bash", command=command))


def test_grep_over_docs_or_config_passes(repo: Path):
    assert _call(repo, "Grep", pattern="x", glob="**/*.yml") is None
    assert _call(repo, "Grep", pattern="x", type="md") is None


def test_no_index_or_disabled_guard_never_intercepts(repo: Path, tmp_path: Path, monkeypatch):
    assert _call(tmp_path, "Grep", pattern="x") is None
    monkeypatch.setenv("CBX_GUARD", "0")
    assert _call(repo, "Grep", pattern="x") is None


def test_msys_cwd_is_understood(repo: Path, monkeypatch):
    monkeypatch.setattr(hooks.os, "name", "nt")
    drive, rest = str(repo).replace("\\", "/").split(":", 1) if ":" in str(repo) else ("", "")
    if not drive:
        pytest.skip("POSIX path has no drive letter")
    assert hooks._cwd({"cwd": f"/{drive.lower()}{rest}"}) == Path(f"{drive}:{rest}")


def test_main_reads_stdin_and_writes_the_reply(repo: Path, monkeypatch, capsys):
    payload = {"session_id": "m", "cwd": str(repo), "tool_name": "Grep",
               "tool_input": {"pattern": "x"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert hooks.main(["guard"]) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert hooks.main(["guard"]) == 0 and capsys.readouterr().out == ""


def test_install_merges_idempotently_and_uninstall_keeps_other_hooks(tmp_path: Path):
    path = tmp_path / "settings.json"
    other = {"type": "command", "command": "my-other-hook"}
    path.write_text(json.dumps({"model": "x", "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [other]}]}}), encoding="utf-8")
    assert scaffold.install_guard_hooks(path) == ["SessionStart", "PreToolUse"]
    assert scaffold.install_guard_hooks(path) == []
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "x" and len(data["hooks"]["PreToolUse"]) == 2
    assert scaffold.uninstall_guard_hooks(path) == ["SessionStart", "PreToolUse"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hooks"] == {"PreToolUse": [{"matcher": "Bash", "hooks": [other]}]}
