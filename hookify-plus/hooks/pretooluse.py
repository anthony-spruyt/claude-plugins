#!/usr/bin/env python3
"""PreToolUse hook executor for hookify-plus.

Evaluates blocking rules before tool execution.
Resets warning state when a subagent is spawned (Task tool).
Uses stderr + exit 2 to ensure messages reach Claude (fix for #12446).
"""

import os
import sys
import json

# CRITICAL: Add plugin root to Python path for imports
PLUGIN_ROOT = os.environ.get('CLAUDE_PLUGIN_ROOT')
if PLUGIN_ROOT and PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

try:
    from core.config_loader import load_rules
    from core.rule_engine import RuleEngine
    from core.state import reset_warning_state
except ImportError as e:
    # If imports fail, allow operation and log error
    print(f"Hookify import error: {e}", file=sys.stderr)
    sys.exit(0)


def main():
    """Main entry point for PreToolUse hook."""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        tool_name = input_data.get('tool_name', '')
        session_id = input_data.get('session_id', '')

        # Reset warning state when spawning a subagent
        # This gives each subagent fresh warnings
        if tool_name == 'Task':
            reset_warning_state(session_id)

        # Map tools to event types
        event = None
        if tool_name == 'Bash':
            event = 'bash'
        elif tool_name in ['Edit', 'Write', 'MultiEdit', 'Update']:
            event = 'file'
        elif tool_name in ['Read', 'Glob', 'Grep', 'LS']:
            event = 'read'

        # Load rules
        rules = load_rules(event=event)

        # Filter to only blocking rules
        block_rules = [r for r in rules if r.action == 'block']

        if not block_rules:
            sys.exit(0)  # No blocking rules, allow

        # Evaluate rules
        engine = RuleEngine()
        result = engine.evaluate_rules(block_rules, input_data)

        # Check if any rule blocked
        is_block = result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'

        if is_block:
            message = result.get('systemMessage', 'Blocked by hookify rule')

            # Show to user via /dev/tty (CLI)
            try:
                with open('/dev/tty', 'w') as tty:
                    tty.write(f"\n🚫 BLOCKED: {message}\n")
            except (OSError, IOError):
                pass

            # Send to Claude via stderr + exit 2 (fix for #12446)
            print(message, file=sys.stderr)
            sys.exit(2)

        sys.exit(0)

    except json.JSONDecodeError:
        sys.exit(0)  # Invalid input, allow operation
    except Exception as e:
        # On any error, allow the operation and log
        print(f"Hookify error: {str(e)}", file=sys.stderr)
        sys.exit(0)


if __name__ == '__main__':
    main()
