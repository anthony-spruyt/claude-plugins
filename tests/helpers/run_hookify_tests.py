#!/usr/bin/env python3
"""Data-driven hookify test runner.

Reads test cases from YAML config and runs them through the hookify rule engine.
Uses the actual hookify implementation for accurate testing.
"""

import sys
import os
import argparse
import glob

# Add plugin core to path for hookify module
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def find_hookify_plugin():
    """Find hookify plugin path - local monorepo or installed."""
    # Local monorepo (preferred for testing)
    local_path = os.path.join(REPO_ROOT, "hookify-plus")
    if os.path.isdir(local_path):
        return local_path

    # Fall back to installed plugin
    home = os.path.expanduser("~")
    installed_patterns = [
        os.path.join(home, ".claude/plugins/cache/claude-plugins/hookify-plus/*/"),
        os.path.join(home, ".claude/plugins/cache/hookify-plus-local/hookify-plus/*/"),
        os.path.join(home, ".claude/plugins/cache/*/hookify-plus/*/"),
    ]
    for pattern in installed_patterns:
        matches = glob.glob(pattern)
        if matches:
            return max(matches)

    raise RuntimeError(
        "No hookify-plus found. Run tests from monorepo root or install plugin."
    )

sys.path.insert(0, find_hookify_plugin())

import yaml
from core import load_rules, RuleEngine


def get_result_type(result: dict) -> str:
    """Determine result type from hookify output.

    Args:
        result: Hookify evaluation result dict

    Returns:
        "block", "warn", or "allow"
    """
    if not result:
        return "allow"
    if result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny':
        return "block"
    if 'systemMessage' in result:
        return "warn"
    return "allow"


def run_tests(config_path: str, verbose: bool = False) -> list:
    """Run all test cases from config file.

    Args:
        config_path: Path to test cases YAML file
        verbose: Print detailed output

    Returns:
        List of failure messages (empty if all passed)
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Set CLAUDE_PLUGIN_ROOT so engine discovers sibling plugins
    hookify_root = os.path.join(repo_root, "hookify-plus")
    os.environ["CLAUDE_PLUGIN_ROOT"] = hookify_root

    # Change to repo root so load_rules() finds .claude/ if present
    original_cwd = os.getcwd()
    os.chdir(repo_root)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        engine = RuleEngine()
        failures = []
        passed = 0

        for test in config.get('test_cases', []):
            name = test.get('name', 'unnamed')
            tool = test.get('tool', 'Bash')
            expect = test.get('expect', 'allow')

            # Build input JSON based on tool type
            if tool == 'Bash':
                input_data = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": test.get('command', '')}
                }
            elif tool in ['Read', 'Edit', 'Write']:
                input_data = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool,
                    "tool_input": {
                        "file_path": test.get('file_path', ''),
                        "content": test.get('content', ''),
                        "new_string": test.get('new_string', ''),
                        "old_string": test.get('old_string', '')
                    }
                }
            else:
                input_data = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool,
                    "tool_input": test.get('tool_input', {})
                }

            # Determine event type for rule loading
            event = "bash" if tool == "Bash" else "file"

            # Load rules (hookify-plus uses cwd, not rules_dir param)
            rules = load_rules(event=event)
            result = engine.evaluate_rules(rules, input_data)

            # Check expectation
            actual = get_result_type(result)

            if actual != expect:
                msg = f"FAIL: {name}: expected {expect}, got {actual}"
                failures.append(msg)
                if verbose:
                    print(f"\033[91m{msg}\033[0m")  # Red
                    print(f"  Input: {input_data}")
                    print(f"  Result: {result}")
            else:
                passed += 1
                if verbose:
                    print(f"\033[92mPASS: {name}\033[0m")  # Green

        # Summary
        total = passed + len(failures)
        print(f"\n{passed}/{total} tests passed")

        return failures
    finally:
        os.chdir(original_cwd)


def main():
    """CLI entry point for running hookify tests."""
    parser = argparse.ArgumentParser(description='Run hookify test cases')
    parser.add_argument('config', help='Path to test cases YAML file')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Print detailed output')
    args = parser.parse_args()

    failures = run_tests(args.config, args.verbose)

    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
