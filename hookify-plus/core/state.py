#!/usr/bin/env python3
"""Rate limiting state management for hookify-plus.

Tracks warning counts per rule to support warn_once and warn_interval.
State is stored in /tmp/claude-hookify-state-{session_id}[-{agent_id}].json with 24h TTL.

Session ID and, inside subagents, agent_id are provided by Claude Code in hook input.
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .config_loader import Rule

STATE_TTL_HOURS = 24
STATE_DIR = Path("/tmp")


class WarningState:
    """Manages rate limiting state for hookify warnings.

    Scoped per session, and per subagent via agent_id, so the main thread
    and each subagent warn independently.
    """

    def __init__(self, session_id: str, agent_id: Optional[str] = None):
        """Initialize state manager.

        Args:
            session_id: Session ID from Claude Code hook input
            agent_id: Subagent ID from hook input; absent on the main thread
        """
        self.session_id = session_id
        self.scope_id = session_id[:12] if session_id else "unknown"
        agent_scope = re.sub(r"[^A-Za-z0-9_-]", "", agent_id or "")[:32]
        if agent_scope:
            self.scope_id += f"-{agent_scope}"
        self.state_file = STATE_DIR / f"claude-hookify-state-{self.scope_id}.json"
        self._cleanup_old_state_files()
        self.state = self._load_state()

    def _cleanup_old_state_files(self):
        """Remove state files older than STATE_TTL_HOURS."""
        try:
            cutoff = time.time() - (STATE_TTL_HOURS * 3600)
            for f in STATE_DIR.glob("claude-hookify-state-*.json"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except (OSError, IOError):
                    pass
        except (OSError, IOError):
            pass  # Ignore if /tmp is inaccessible

    def _load_state(self) -> dict:
        """Load state from file, return empty if stale or missing."""
        if not self.state_file.exists():
            return {"created_at": datetime.now().isoformat(), "session_id": self.session_id, "rules": {}}

        try:
            with open(self.state_file) as f:
                state = json.load(f)

            created_str = state.get("created_at", "1970-01-01T00:00:00")
            try:
                created = datetime.fromisoformat(created_str)
            except ValueError:
                created = datetime(1970, 1, 1)

            if datetime.now() - created > timedelta(hours=STATE_TTL_HOURS):
                return {"created_at": datetime.now().isoformat(), "session_id": self.session_id, "rules": {}}

            return state
        except (json.JSONDecodeError, IOError, OSError):
            return {"created_at": datetime.now().isoformat(), "session_id": self.session_id, "rules": {}}

    def should_warn(self, rule: "Rule") -> bool:
        """Check if warning should be shown based on rate limiting.

        Args:
            rule: Rule with warn_once and/or warn_interval settings

        Returns:
            True if warning should be shown, False if suppressed
        """
        if not rule.warn_once and rule.warn_interval <= 0:
            return True

        rule_state = self.state.get("rules", {}).get(rule.name, {})
        warn_count = rule_state.get("warn_count", 0)

        if rule.warn_once:
            return warn_count == 0
        elif rule.warn_interval > 0:
            # Warn on 0, N, 2N, 3N, ...
            return warn_count % rule.warn_interval == 0

        return True

    def record_match(self, rule: "Rule"):
        """Record that a rule matched (regardless of whether warning was shown).

        This increments the counter so rate limiting works correctly.
        Call this for every match, not just when warning is shown.

        Args:
            rule: Rule that matched
        """
        if rule.name not in self.state.get("rules", {}):
            self.state.setdefault("rules", {})[rule.name] = {"warn_count": 0}

        self.state["rules"][rule.name]["warn_count"] += 1
        self.state["rules"][rule.name]["last_matched_at"] = datetime.now().isoformat()
        self._save_state()

    def _save_state(self):
        """Atomically write state to file."""
        try:
            tmp_file = self.state_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(self.state, f, indent=2)
            tmp_file.rename(self.state_file)  # Atomic on POSIX
        except (IOError, OSError) as e:
            import sys
            print(f"Warning: Could not save hookify state: {e}", file=sys.stderr)
