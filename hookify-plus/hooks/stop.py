#!/usr/bin/env python3
"""Stop hook executor for hookify plugin.

This script is called by Claude Code when agent wants to stop.
It reads .claude/hookify.*.local.md files and evaluates stop rules.
"""

import json
import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
if PLUGIN_ROOT and PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

try:
    from core.config_loader import load_rules
    from core.rule_engine import RuleEngine
except ImportError as e:
    error_msg = {"systemMessage": f"Hookify import error: {e}"}
    print(json.dumps(error_msg), file=sys.stdout)
    sys.exit(0)


def main():
    """Main entry point for Stop hook."""
    try:
        input_data = json.load(sys.stdin)
        rules = load_rules(event="stop")
        engine = RuleEngine()
        result = engine.evaluate_rules(rules, input_data)
        print(json.dumps(result), file=sys.stdout)

    except Exception as e:
        # Fail open: an error must not stop Claude from stopping
        error_output = {"systemMessage": f"Hookify error: {e!s}"}
        print(json.dumps(error_output), file=sys.stdout)

    finally:
        # Claude Code only reads the stdout JSON, block decision included, on exit 0
        sys.exit(0)


if __name__ == "__main__":
    main()
