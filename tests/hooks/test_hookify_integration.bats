#!/usr/bin/env bats

# End-to-end tests: pipe hook JSON into the real hook scripts from this repo

load '/usr/local/lib/bats/bats-support/load'
load '/usr/local/lib/bats/bats-assert/load'

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)}"

setup() {
  # Mirror the plugin cache layout: {marketplace}/{plugin}/{version}/
  local cache="$BATS_TEST_TMPDIR/cache"
  mkdir -p "$cache/hookify-plus"
  ln -s "$REPO_ROOT/hookify-plus" "$cache/hookify-plus/test"
  for plugin in security-hooks best-practices; do
    mkdir -p "$cache/$plugin/test/.in_use"
    ln -s "$REPO_ROOT/$plugin/hookify-plus" "$cache/$plugin/test/hookify-plus"
  done
  export CLAUDE_PLUGIN_ROOT="$cache/hookify-plus/test"
  # Isolate from project and global rules on this machine
  export HOME="$BATS_TEST_TMPDIR"
  cd "$BATS_TEST_TMPDIR" || return
}

hook() {
  local script="$1" command="$2" event
  case "$script" in
  pretooluse.py) event=PreToolUse ;;
  posttooluse.py) event=PostToolUse ;;
  esac
  jq -nc --arg cmd "$command" --arg sid "bats-$BATS_TEST_NUMBER-$$" --arg ev "$event" \
    '{session_id: $sid, hook_event_name: $ev, tool_name: "Bash", tool_input: {command: $cmd}}' |
    python3 "$CLAUDE_PLUGIN_ROOT/hooks/$script"
}

@test "hookify integration: all test cases pass" {
  run python3 "$REPO_ROOT/tests/helpers/run_hookify_tests.py" \
    "$REPO_ROOT/tests/hooks/hookify_test_cases.yaml"
  assert_success
}

@test "pretooluse: block rule exits 2 with the rule message" {
  run hook pretooluse.py "sops -d secrets.yaml"
  assert_equal "$status" 2
  assert_output --partial "[block-sops-decrypt]"
}

@test "pretooluse: allowed command exits 0 silently" {
  run hook pretooluse.py "echo hello world"
  assert_success
  assert_output ""
}

@test "pretooluse: warn rules do not run before the tool" {
  run hook pretooluse.py "cat README.md"
  assert_success
  assert_output ""
}

@test "pretooluse: mask_data ignores prose in a commit message" {
  run hook pretooluse.py 'git commit -m "docs: explain set > file is blocked"'
  assert_success
}

@test "pretooluse: mask_data still blocks a dump after the message" {
  run hook pretooluse.py 'git commit -m "fix: x" && env'
  assert_equal "$status" 2
  assert_output --partial "[block-env-dump]"
}

@test "posttooluse: warn rule exits 2 with the rule message" {
  run hook posttooluse.py "cat README.md"
  assert_equal "$status" 2
  assert_output --partial "[warn-use-read-tool]"
}

@test "pretooluse: invalid JSON fails open" {
  run bash -c "echo 'not json' | python3 '$CLAUDE_PLUGIN_ROOT/hooks/pretooluse.py'"
  assert_success
}
