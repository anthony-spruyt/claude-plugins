#!/usr/bin/env python3
"""Unit tests for the PreToolUse hook's subagent warning reset."""

import json
import os
import subprocess
import sys
import uuid

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_ROOT = os.path.join(REPO_ROOT, "hookify-plus")
sys.path.insert(0, PLUGIN_ROOT)

from core.state import STATE_DIR


def run_hook(tool_name, session_id, cwd):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT, "HOME": str(cwd)}
    payload = {"tool_name": tool_name, "session_id": session_id, "tool_input": {}}
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN_ROOT, "hooks", "pretooluse.py")],
        input=json.dumps(payload), capture_output=True, text=True, cwd=cwd, env=env,
    )


@pytest.fixture
def state_file():
    session_id = uuid.uuid4().hex
    path = STATE_DIR / f"claude-hookify-state-{session_id[:12]}.json"
    path.write_text("{}")
    yield session_id, path
    path.unlink(missing_ok=True)


class TestSubagentReset:
    @pytest.mark.parametrize("tool_name", ["Agent", "Task"])
    def test_subagent_tool_resets_warning_state(self, tool_name, state_file, tmp_path):
        session_id, path = state_file
        run_hook(tool_name, session_id, tmp_path)
        assert not path.exists()

    def test_other_tools_keep_warning_state(self, state_file, tmp_path):
        session_id, path = state_file
        run_hook("Bash", session_id, tmp_path)
        assert path.exists()
