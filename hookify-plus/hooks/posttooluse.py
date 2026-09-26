#!/usr/bin/env python3
"""PostToolUse hook executor for hookify-plus.

Evaluates warning rules after tool execution.
Supports rate limiting via warn_once and warn_interval.
Uses stderr + exit 2 to ensure messages reach Claude (fix for #12446).
"""

import os
import sys
import json

PLUGIN_ROOT = os.environ.get('CLAUDE_PLUGIN_ROOT')
if PLUGIN_ROOT and PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

try:
    from core.config_loader import load_rules
    from core.rule_engine import RuleEngine
    from core.state import WarningState
    from core.tools import event_for_tool
except ImportError as e:
    print(f"Hookify import error: {e}", file=sys.stderr)
    sys.exit(0)


def main():
    """Main entry point for PostToolUse hook."""
    try:
        input_data = json.load(sys.stdin)

        tool_name = input_data.get('tool_name', '')
        session_id = input_data.get('session_id', '')

        rules = load_rules(event=event_for_tool(tool_name))

        warn_rules = [r for r in rules if r.action == 'warn']

        if not warn_rules:
            sys.exit(0)

        state = WarningState(session_id)

        engine = RuleEngine()
        matching_rules = []

        for rule in warn_rules:
            test_result = engine.evaluate_rules([rule], input_data)
            if test_result.get('systemMessage'):
                if state.should_warn(rule):
                    matching_rules.append(rule)
                # Always record match for rate limiting
                state.record_match(rule)

        if not matching_rules:
            sys.exit(0)

        messages = [f"**[{r.name}]**\n{r.message}" for r in matching_rules]
        combined_message = "\n\n".join(messages)

        # Send to Claude via stderr + exit 2 (fix for #12446)
        print(combined_message, file=sys.stderr)
        sys.exit(2)

    except json.JSONDecodeError:
        sys.exit(0)
    except Exception as e:
        print(f"Hookify error: {str(e)}", file=sys.stderr)
        sys.exit(0)


if __name__ == '__main__':
    main()
