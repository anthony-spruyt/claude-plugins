#!/usr/bin/env python3
"""Unit tests for per-agent warn_once scoping."""

import json
import os
import subprocess
import sys
import uuid

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_ROOT = os.path.join(REPO_ROOT, "hookify-plus")
sys.path.insert(0, PLUGIN_ROOT)

from core.state import STATE_DIR, WarningState

RULE = """---
name: warn-test-once
enabled: true
event: bash
pattern: warnme
action: warn
warn_once: true
---
test warning
"""


def run(hook, cwd, session_id, tool_name="Bash", agent_id=None):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT, "HOME": str(cwd)}
    payload = {"tool_name": tool_name, "session_id": session_id,
               "tool_input": {"command": "echo warnme"}}
    if agent_id:
        payload["agent_id"] = agent_id
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN_ROOT, "hooks", hook)],
        input=json.dumps(payload), capture_output=True, text=True, cwd=cwd, env=env,
    ).returncode


def warns(cwd, session_id, agent_id=None):
    return run("posttooluse.py", cwd, session_id, agent_id=agent_id) == 2


@pytest.fixture
def project(tmp_path):
    rule_dir = tmp_path / ".claude" / "hookify-plus"
    rule_dir.mkdir(parents=True)
    (rule_dir / "warn-test-once.md").write_text(RULE)
    session_id = uuid.uuid4().hex
    yield tmp_path, session_id
    for f in STATE_DIR.glob(f"claude-hookify-state-{session_id[:12]}*.json"):
        f.unlink()


class TestWarnScope:
    def test_main_thread_warns_once(self, project):
        cwd, session_id = project
        assert warns(cwd, session_id)
        assert not warns(cwd, session_id)

    def test_each_subagent_warns_once(self, project):
        cwd, session_id = project
        assert warns(cwd, session_id)
        assert warns(cwd, session_id, agent_id="agent-a")
        assert not warns(cwd, session_id, agent_id="agent-a")
        assert warns(cwd, session_id, agent_id="agent-b")

    def test_spawning_subagent_keeps_main_thread_state(self, project):
        cwd, session_id = project
        assert warns(cwd, session_id)
        run("pretooluse.py", cwd, session_id, tool_name="Agent")
        assert not warns(cwd, session_id)

    def test_agent_id_is_sanitized_in_state_path(self):
        state = WarningState(uuid.uuid4().hex, agent_id="../../etc/x")
        assert state.state_file.parent == STATE_DIR
        assert "/" not in state.state_file.name
