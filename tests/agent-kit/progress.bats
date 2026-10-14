#!/usr/bin/env bats
#
# progress.sh keeps one progress-notes system for the main session and opted-in subagents.
# It reads a hook payload on stdin, takes the event name as $1 and never blocks a tool call.

bats_require_minimum_version 1.5.0

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
PLUGIN="${REPO_ROOT}/agent-kit"
SCRIPT="${PLUGIN}/scripts/progress.sh"
AGENT=a1b2c3d4e5
SID=sess1

setup() {
  TMP="$(mktemp -d)"
  export CLAUDE_PROJECT_DIR="${TMP}/project"
  mkdir -p "${CLAUDE_PROJECT_DIR}" "${TMP}/claude/${SID}/subagents"
  git init -q "${CLAUDE_PROJECT_DIR}"
  DIR="${CLAUDE_PROJECT_DIR}/.agent-progress"
  SESSION_FILE="${TMP}/claude/${SID}.jsonl"
  SUB_FILE="${TMP}/claude/${SID}/subagents/agent-${AGENT}.jsonl"
  : >"${SESSION_FILE}"
  : >"${SUB_FILE}"
  MAIN_NOTES="${DIR}/${SID}.md"
  SUB_NOTES="${DIR}/agent-${AGENT}.md"
  CWD="${CLAUDE_PROJECT_DIR}"
  SCRIPT_TO_RUN="${SCRIPT}"
}

teardown() {
  rm -rf "${TMP}"
}

# Payload builders. Subagent hooks carry the main session's transcript_path, as the live probe showed.
main_in() {
  jq -nc --arg ev "$1" --arg src "${2:-}" --arg t "${SESSION_FILE}" --arg cwd "${CWD}" --arg s "${SID}" \
    '{session_id: $s, transcript_path: $t, cwd: $cwd, hook_event_name: $ev}
     + (if $src != "" then {source: $src} else {} end)'
}

sub_in() {
  jq -nc --arg ev "$1" --arg a "$2" --arg ty "${3-builder}" --arg t "${SESSION_FILE}" --arg cwd "${CWD}" --arg s "${SID}" \
    '{session_id: $s, transcript_path: $t, cwd: $cwd, hook_event_name: $ev, agent_id: $a, agent_type: $ty}'
}

fire() {
  local ev=$1 payload=$2
  run --separate-stderr bash "${SCRIPT_TO_RUN}" "${ev}" <<<"${payload}"
}

start() { fire SessionStart "$(main_in SessionStart "${1:-startup}")"; }
main_pre() { fire PreToolUse "$(main_in PreToolUse)"; }
main_end() { fire SessionEnd "$(main_in SessionEnd)"; }
sub_start() { fire SubagentStart "$(sub_in SubagentStart "${1-${AGENT}}" "${2-builder}")"; }
sub_pre() { fire PreToolUse "$(sub_in PreToolUse "${1-${AGENT}}" "${2-builder}")"; }
sub_stop() { fire SubagentStop "$(sub_in SubagentStop "${1-${AGENT}}" "${2-builder}")"; }

compact_main() {
  printf '%s\n' '{"type":"system","subtype":"compact_boundary","content":"Conversation compacted"}' >>"${SESSION_FILE}"
}

compact_sub() {
  printf '%s\n' '{"type":"system","subtype":"compact_boundary","content":"Conversation compacted"}' >>"${SUB_FILE}"
}

context() {
  jq -r '.hookSpecificOutput.additionalContext' <<<"${output}"
}

event_name() {
  jq -r '.hookSpecificOutput.hookEventName' <<<"${output}"
}

assert_silent() {
  [ "${status}" -eq 0 ]
  [ -z "${output}" ]
}

assert_injected() {
  [ "${status}" -eq 0 ]
  [[ "$(context)" == *"$1"* ]]
}

no_files() {
  [ ! -e "${DIR}" ] || [ -z "$(ls -A "${DIR}")" ]
}

# --- SessionStart ----------------------------------------------------------

@test "SessionStart startup gives the notes path, the rule and says none are written" {
  start startup
  [ "$(event_name)" = "SessionStart" ]
  assert_injected "${MAIN_NOTES}"
  [[ "$(context)" == *"none written yet"* ]]
  [[ "$(context)" == *"more than one step"* ]]
}

@test "SessionStart resume, clear and fork behave like startup" {
  for src in resume clear fork; do
    rm -rf "${DIR}"
    start "${src}"
    assert_injected "${MAIN_NOTES}"
    [ "$(event_name)" = "SessionStart" ]
  done
}

@test "SessionStart with existing notes includes them and says to check git log" {
  mkdir -p "${DIR}"
  printf 'GOAL: ship the thing\nNEXT: run tests\n' >"${MAIN_NOTES}"
  start resume
  assert_injected "GOAL: ship the thing"
  [[ "$(context)" == *"NEXT: run tests"* ]]
  [[ "$(context)" == *"git log"* ]]
  [[ "$(context)" != *"none written yet"* ]]
}

@test "existing notes are delivered when stat rejects -c, as BSD stat does" {
  mkdir -p "${DIR}" "${TMP}/bsdbin"
  printf '#!/bin/sh\nexit 1\n' >"${TMP}/bsdbin/stat"
  chmod +x "${TMP}/bsdbin/stat"
  printf 'GOAL: portable\n' >"${MAIN_NOTES}"
  PATH="${TMP}/bsdbin:${PATH}" start resume
  assert_injected "GOAL: portable"
  rm -f "${MAIN_NOTES}"
  printf 'SECRET\n' >"${TMP}/target.md"
  ln "${TMP}/target.md" "${MAIN_NOTES}"
  PATH="${TMP}/bsdbin:${PATH}" start resume
  [[ "$(context)" != *"SECRET"* ]]
}

@test "SessionStart with an empty notes file says none are written" {
  mkdir -p "${DIR}"
  : >"${MAIN_NOTES}"
  start startup
  assert_injected "none written yet"
}

@test "SessionStart compact outputs nothing and writes nothing" {
  start compact
  assert_silent
  no_files
}

@test "SessionStart compact stays silent even when the payload names an agent" {
  fire SessionStart "$(jq -c '. + {source: "compact", agent_id: "x", agent_type: "builder"}' <<<"$(main_in SessionStart)")"
  assert_silent
  no_files
}

@test "SessionStart with another source is silent" {
  start somethingelse
  assert_silent
}

@test "SessionStart saves the notes path and creates the folder with an ignoring .gitignore" {
  start startup
  [ -s "${DIR}/${SID}.state" ]
  grep -qxF "${MAIN_NOTES}" "${DIR}/${SID}.state"
  grep -qxF '*' "${DIR}/.gitignore"
}

@test "SessionStart keeps an existing .gitignore" {
  mkdir -p "${DIR}"
  printf '*\n!.gitignore\n' >"${DIR}/.gitignore"
  start startup
  [ "$(cat "${DIR}/.gitignore")" = $'*\n!.gitignore' ]
}

@test "SessionStart on a second start resets claims so a stale claim cannot lock out a compaction" {
  start startup
  : >"${DIR}/${SID}.claim-1"
  start resume
  [ ! -e "${DIR}/${SID}.claim-1" ]
}

# --- notes path resolution --------------------------------------------------

@test "a cwd inside a worktree of the project puts the notes in the worktree root" {
  git -C "${CLAUDE_PROJECT_DIR}" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m init
  git -C "${CLAUDE_PROJECT_DIR}" worktree add -q "${TMP}/wt" -b wt
  mkdir -p "${TMP}/wt/sub"
  CWD="${TMP}/wt/sub"
  start startup
  assert_injected "${TMP}/wt/.agent-progress/${SID}.md"
  grep -qxF "${TMP}/wt/.agent-progress/${SID}.md" "${DIR}/${SID}.state"
}

@test "a cwd in an unrelated repo falls back to the project" {
  git init -q "${TMP}/other"
  CWD="${TMP}/other"
  start startup
  assert_injected "${MAIN_NOTES}"
}

@test "notes written in the project before cwd moved to a worktree are used and both paths shown" {
  git -C "${CLAUDE_PROJECT_DIR}" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m init
  git -C "${CLAUDE_PROJECT_DIR}" worktree add -q "${TMP}/wt" -b wt
  mkdir -p "${DIR}"
  printf 'PROJECT NOTES\n' >"${MAIN_NOTES}"
  CWD="${TMP}/wt"
  start resume
  assert_injected "PROJECT NOTES"
  [[ "$(context)" == *"${MAIN_NOTES}"* ]]
  [[ "$(context)" == *"${TMP}/wt/.agent-progress/${SID}.md"* ]]
}

@test "a project that is not a git checkout is silent" {
  rm -rf "${CLAUDE_PROJECT_DIR}/.git"
  start startup
  assert_silent
}

@test "a missing cwd falls back to the project dir" {
  fire SessionStart "$(jq -c 'del(.cwd)' <<<"$(main_in SessionStart startup)")"
  assert_injected "${MAIN_NOTES}"
}

# --- main session compaction -------------------------------------------------

@test "main PreToolUse after start is silent" {
  start startup
  main_pre
  assert_silent
}

@test "a compaction makes the next main tool call inject the notes, once" {
  start startup
  printf 'GOAL: ship the thing\n' >"${MAIN_NOTES}"
  compact_main
  main_pre
  [ "$(event_name)" = "PreToolUse" ]
  assert_injected "GOAL: ship the thing"
  [[ "$(context)" == *"compacted"* ]]
  [[ "$(context)" == *"more than one step"* ]]
  main_pre
  assert_silent
  compact_main
  main_pre
  assert_injected "GOAL: ship the thing"
}

@test "a compaction with no notes yet points at the path" {
  start startup
  compact_main
  main_pre
  assert_injected "${MAIN_NOTES}"
  [[ "$(context)" == *"none written yet"* ]]
}

@test "compactions already in the transcript at resume are not re-injected" {
  compact_main
  compact_main
  start resume
  main_pre
  assert_silent
  compact_main
  main_pre
  assert_injected "compacted"
}

@test "text that merely mentions compact_boundary is not a compaction" {
  start startup
  printf '%s\n' '{"type":"user","message":{"content":"grep \"subtype\":\"compact_boundary\" file"}}' >>"${SESSION_FILE}"
  main_pre
  assert_silent
}

@test "a main PreToolUse with no saved state starts the notes once" {
  main_pre
  assert_injected "${MAIN_NOTES}"
  main_pre
  assert_silent
}

@test "a missing session transcript still starts and stays silent after" {
  rm "${SESSION_FILE}"
  start startup
  main_pre
  assert_silent
}

@test "parallel main calls after one compaction inject exactly once" {
  start startup
  printf 'GOAL: ship the thing\n' >"${MAIN_NOTES}"
  compact_main
  payload="$(main_in PreToolUse)"
  for i in 1 2 3 4 5 6; do
    bash "${SCRIPT}" PreToolUse <<<"${payload}" >"${TMP}/out.${i}" &
  done
  wait
  [ "$(cat "${TMP}"/out.* | grep -c additionalContext)" -eq 1 ]
}

@test "a subagent compaction does not make the main session inject" {
  start startup
  sub_start
  compact_sub
  main_pre
  assert_silent
}

# --- main session end --------------------------------------------------------

@test "SessionEnd removes the session's state and claims and keeps its notes" {
  start startup
  printf 'GOAL: keep me\n' >"${MAIN_NOTES}"
  compact_main
  main_pre
  [ -e "${DIR}/${SID}.state" ]
  compgen -G "${DIR}/${SID}.claim-*" >/dev/null
  main_end
  assert_silent
  [ ! -e "${DIR}/${SID}.state" ]
  if compgen -G "${DIR}/${SID}.claim-*" >/dev/null; then return 1; fi
  [ "$(cat "${MAIN_NOTES}")" = "GOAL: keep me" ]
}

@test "SessionEnd leaves other sessions and agents alone" {
  start startup
  sub_start
  mkdir -p "${DIR}"
  : >"${DIR}/other.state"
  : >"${DIR}/other.claim-0"
  main_end
  [ -e "${DIR}/other.state" ]
  [ -e "${DIR}/other.claim-0" ]
  [ -e "${DIR}/agent-${AGENT}.state" ]
}

@test "SessionEnd does not create the notes folder" {
  main_end
  [ ! -e "${DIR}" ]
}

@test "SessionEnd does not follow a symlinked state file" {
  mkdir -p "${DIR}"
  printf 'x\n' >"${TMP}/target.state"
  ln -s "${TMP}/target.state" "${DIR}/${SID}.state"
  main_end
  [ -L "${DIR}/${SID}.state" ]
  [ "$(cat "${TMP}/target.state")" = "x" ]
}

# --- subagents: opt-in and ids ----------------------------------------------

@test "SubagentStart for builder gives the notes path, the rule and says none are written" {
  sub_start
  [ "$(event_name)" = "SubagentStart" ]
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"none written yet"* ]]
  [[ "$(context)" == *"more than one step"* ]]
  [[ "$(context)" == *"as soon as you start"* ]]
  [[ "$(context)" == *"after each commit"* ]]
}

@test "the subagent start text names no tool and leaves the one-step skip to the rule" {
  sub_start
  text=$(context)
  [[ "${text}" != *"workspace.sh"* ]]
  [[ "${text}" != *"Notes are required"* ]]
  [[ "${text}" == *"one-step"* ]]
}

@test "agents that are not listed get nothing and write nothing" {
  for type in general-purpose agent-kit:builder Builder "builder " ""; do
    sub_start "${AGENT}" "${type}"
    assert_silent
    sub_pre "${AGENT}" "${type}"
    assert_silent
    sub_stop "${AGENT}" "${type}"
    assert_silent
  done
  no_files
}

@test "a subagent payload without agent_type is silent" {
  fire SubagentStart "$(jq -c 'del(.agent_type)' <<<"$(sub_in SubagentStart "${AGENT}")")"
  assert_silent
  no_files
}

# --- config -----------------------------------------------------------------
with_plugin_copy() {
  mkdir -p "${TMP}/plugin"
  cp -r "${PLUGIN}/scripts" "${PLUGIN}/config" "${TMP}/plugin/"
  SCRIPT_TO_RUN="${TMP}/plugin/scripts/progress.sh"
}

with_plugin_config() {
  with_plugin_copy
  printf '%b' "$1" >"${TMP}/plugin/config/progress.json"
}

with_repo_config() {
  mkdir -p "${CLAUDE_PROJECT_DIR}/.claude"
  printf '%b' "$1" >"${CLAUDE_PROJECT_DIR}/.claude/agent-kit.json"
}

@test "the shipped progress.json default holds builder, 10, 200000 and 90/95" {
  [ "$(jq -c . "${PLUGIN}/config/progress.json")" = '{"notesAgents":["builder"],"nudgeAfterToolCalls":10,"compactAtTokens":200000,"warnAtPercent":[90,95]}' ]
}

@test "the old plain-text config files are gone" {
  [ ! -e "${PLUGIN}/config/notes-agents" ]
  [ ! -e "${PLUGIN}/config/notes-nudge-calls" ]
}

@test "the default opts builder in and nobody else" {
  sub_start
  assert_injected "${SUB_NOTES}"
  sub_start "${AGENT}" general-purpose
  assert_silent
  sub_start "${AGENT}" agent-kit:reviewer
  assert_silent
}

@test "a repo notesAgents replaces the default list" {
  with_repo_config '{"progress":{"notesAgents":["agent-kit:reviewer","other"]}}'
  sub_start "${AGENT}" agent-kit:reviewer
  assert_injected "${SUB_NOTES}"
  rm -rf "${DIR}"
  sub_start "${AGENT}" builder
  assert_silent
  no_files
}

@test "a repo notesAgents of an empty array opts nobody in" {
  with_repo_config '{"progress":{"notesAgents":[]}}'
  sub_start
  assert_silent
  no_files
}

@test "a plugin default with another list opts those in" {
  with_plugin_config '{"notesAgents":["agent-kit:reviewer"],"nudgeAfterToolCalls":10}'
  sub_start "${AGENT}" agent-kit:reviewer
  assert_injected "${SUB_NOTES}"
  rm -rf "${DIR}"
  sub_start
  assert_silent
}

@test "a repo nudgeAfterToolCalls override keeps the default notesAgents" {
  with_repo_config '{"progress":{"nudgeAfterToolCalls":15}}'
  sub_start
  assert_injected "${SUB_NOTES}"
  tool_calls 14
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"15 tool calls"* ]]
}

@test "a repo notesAgents override keeps the default threshold" {
  with_repo_config '{"progress":{"notesAgents":["builder","x"]}}'
  sub_start
  tool_calls 9
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"10 tool calls"* ]]
}

@test "a repo override beats a plugin default; the plugin default beats the built-in" {
  with_plugin_config '{"notesAgents":["a"],"nudgeAfterToolCalls":4}'
  with_repo_config '{"progress":{"nudgeAfterToolCalls":6}}'
  sub_start "${AGENT}" a
  assert_injected "${SUB_NOTES}"
  tool_calls 5
  sub_pre "${AGENT}" a
  assert_silent
  tool_calls 1
  sub_pre "${AGENT}" a
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"6 tool calls"* ]]
}

@test "a whole-number threshold written as 15.0 is accepted as 15" {
  with_repo_config '{"progress":{"nudgeAfterToolCalls":15.0}}'
  sub_start
  tool_calls 14
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"15 tool calls"* ]]
}

@test "a whole-number threshold written as 1e1 or 6.00000000000000001 is accepted, not replaced by the plugin default" {
  with_plugin_config '{"notesAgents":["builder"],"nudgeAfterToolCalls":4}'
  with_repo_config '{"progress":{"nudgeAfterToolCalls":1e1}}'
  sub_start
  tool_calls 9
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"10 tool calls"* ]]
  rm -rf "${DIR}"
  : >"${SUB_FILE}"
  with_repo_config '{"progress":{"nudgeAfterToolCalls":6.00000000000000001}}'
  sub_start
  tool_calls 5
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"6 tool calls"* ]]
}

@test "a fractional repo threshold of 6.5 falls back to the plugin default" {
  with_plugin_config '{"notesAgents":["builder"],"nudgeAfterToolCalls":4}'
  with_repo_config '{"progress":{"nudgeAfterToolCalls":6.5}}'
  sub_start
  tool_calls 3
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"4 tool calls"* ]]
}

@test "a symlinked plugin default is still used" {
  with_plugin_copy
  printf '{"notesAgents":["other"],"nudgeAfterToolCalls":4}' >"${TMP}/real-default.json"
  rm -f "${TMP}/plugin/config/progress.json"
  ln -s "${TMP}/real-default.json" "${TMP}/plugin/config/progress.json"
  sub_start "${AGENT}" other
  assert_injected "${SUB_NOTES}"
  tool_calls 3
  sub_pre "${AGENT}" other
  assert_silent
  tool_calls 1
  sub_pre "${AGENT}" other
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"4 tool calls"* ]]
}

@test "a repo notesAgents of the wrong type falls back to the default list" {
  for bad in '"builder"' '{"a":1}' '[1]' '[""]' '["ok",""]' '[["builder"]]' 'null' '5'; do
    rm -rf "${DIR}"
    with_repo_config "{\"progress\":{\"notesAgents\":${bad}}}"
    sub_start "${AGENT}" other
    assert_silent
    sub_start
    assert_injected "${SUB_NOTES}"
  done
}

@test "a repo nudgeAfterToolCalls of the wrong type or range falls back to the default 10" {
  for bad in '"3"' '0' '-4' '3.5' '1000000' '99999999999999999999' 'null' 'true' '[3]' '{}'; do
    rm -rf "${DIR}"
    : >"${SUB_FILE}"
    with_repo_config "{\"progress\":{\"nudgeAfterToolCalls\":${bad}}}"
    sub_start
    tool_calls 9
    sub_pre
    assert_silent
    tool_calls 1
    sub_pre
    assert_injected "${SUB_NOTES}"
    [[ "$(context)" == *"10 tool calls"* ]]
  done
}

@test "a bad repo key does not spoil the other repo key" {
  with_repo_config '{"progress":{"notesAgents":"x","nudgeAfterToolCalls":3}}'
  sub_start
  assert_injected "${SUB_NOTES}"
  tool_calls 3
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"3 tool calls"* ]]
}

@test "the upper bound 999999 is accepted" {
  with_repo_config '{"progress":{"nudgeAfterToolCalls":999999}}'
  sub_start
  tool_calls 50
  sub_pre
  assert_silent
}

@test "an unparseable or non-object repo file means the defaults" {
  for bad in '' 'not json' '{"progress":' '[1,2]' '"progress"' 'null' '{"progress":[1]}' '{"progress":null}' '{"other":{}}'; do
    rm -rf "${DIR}"
    : >"${SUB_FILE}"
    with_repo_config "${bad}"
    sub_start "${AGENT}" other
    assert_silent
    sub_start
    assert_injected "${SUB_NOTES}"
    tool_calls 10
    sub_pre
    assert_injected "${SUB_NOTES}"
    [[ "$(context)" == *"10 tool calls"* ]]
  done
}

@test "a missing repo file means the defaults" {
  [ ! -e "${CLAUDE_PROJECT_DIR}/.claude/agent-kit.json" ]
  sub_start
  assert_injected "${SUB_NOTES}"
}

@test "a symlinked repo override is ignored" {
  mkdir -p "${CLAUDE_PROJECT_DIR}/.claude"
  printf '{"progress":{"notesAgents":["other"],"nudgeAfterToolCalls":3}}' >"${TMP}/elsewhere.json"
  ln -s "${TMP}/elsewhere.json" "${CLAUDE_PROJECT_DIR}/.claude/agent-kit.json"
  sub_start "${AGENT}" other
  assert_silent
  sub_start
  assert_injected "${SUB_NOTES}"
  tool_calls 3
  sub_pre
  assert_silent
}

@test "a repo override under a symlinked .claude folder is ignored" {
  mkdir -p "${TMP}/realclaude"
  printf '{"progress":{"notesAgents":["other"]}}' >"${TMP}/realclaude/agent-kit.json"
  ln -s "${TMP}/realclaude" "${CLAUDE_PROJECT_DIR}/.claude"
  sub_start "${AGENT}" other
  assert_silent
}

@test "a repo override that is not a regular file is ignored" {
  mkdir -p "${CLAUDE_PROJECT_DIR}/.claude/agent-kit.json"
  sub_start "${AGENT}" other
  assert_silent
  sub_start
  assert_injected "${SUB_NOTES}"
}

@test "a missing plugin default falls back to builder and 10" {
  with_plugin_copy
  rm -f "${TMP}/plugin/config/progress.json"
  sub_start "${AGENT}" other
  assert_silent
  sub_start
  assert_injected "${SUB_NOTES}"
  tool_calls 9
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
}

@test "a broken plugin default falls back to builder and 10; a repo override still applies" {
  with_plugin_config 'not json'
  sub_start "${AGENT}" other
  assert_silent
  sub_start
  assert_injected "${SUB_NOTES}"
  with_repo_config '{"progress":{"notesAgents":["other"]}}'
  rm -rf "${DIR}"
  sub_start "${AGENT}" other
  assert_injected "${SUB_NOTES}"
}

@test "a plugin default with bad values falls back per key" {
  with_plugin_config '{"notesAgents":"builder","nudgeAfterToolCalls":0}'
  sub_start
  assert_injected "${SUB_NOTES}"
  tool_calls 9
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
}

@test "an agent_type that looks like a comment or has spaces matches only exactly" {
  with_repo_config '{"progress":{"notesAgents":["# who","two words"]}}'
  sub_start "${AGENT}" "two words"
  assert_injected "${SUB_NOTES}"
  rm -rf "${DIR}"
  sub_start "${AGENT}" "two"
  assert_silent
}

@test "a leading agent- on the agent_id is stripped; both forms share one notes file and state" {
  sub_start "agent-${AGENT}"
  assert_injected "${DIR}/agent-${AGENT}.md"
  [[ "$(context)" != *"agent-agent-"* ]]
  [ -e "${DIR}/agent-${AGENT}.state" ]
  [ ! -e "${DIR}/agent-agent-${AGENT}.state" ]
  sub_pre "${AGENT}"
  assert_silent
}

@test "subagent notes live in the project folder, not in the cwd's checkout" {
  git init -q "${TMP}/other"
  CWD="${TMP}/other"
  sub_start
  assert_injected "${SUB_NOTES}"
  [ ! -e "${TMP}/other/.agent-progress" ]
}

@test "SubagentStart with existing notes includes them and does not say none are written" {
  mkdir -p "${DIR}"
  printf 'OLD NOTES\n' >"${SUB_NOTES}"
  sub_start
  assert_injected "OLD NOTES"
  [[ "$(context)" != *"none written yet"* ]]
  [[ "$(context)" == *"git log"* ]]
}

@test "SubagentStart with an empty notes file asks for them" {
  mkdir -p "${DIR}"
  : >"${SUB_NOTES}"
  sub_start
  assert_injected "none written yet"
}

@test "SubagentStart on resume injects again and resets the compaction count" {
  sub_start
  compact_sub
  sub_start
  assert_injected "${SUB_NOTES}"
  sub_pre
  assert_silent
  compact_sub
  sub_pre
  assert_injected "compacted"
}

@test "a SubagentStart that saw compactions already in the transcript does not re-inject them" {
  compact_sub
  sub_start
  sub_pre
  assert_silent
}

# --- subagent compaction -----------------------------------------------------

@test "subagent PreToolUse after start is silent" {
  sub_start
  sub_pre
  assert_silent
}

@test "a subagent compaction makes its next tool call inject the notes, once" {
  sub_start
  printf 'GOAL: ship the thing\nNEXT: run tests\n' >"${SUB_NOTES}"
  compact_sub
  sub_pre
  [ "$(event_name)" = "PreToolUse" ]
  assert_injected "GOAL: ship the thing"
  [[ "$(context)" == *"NEXT: run tests"* ]]
  [[ "$(context)" == *"compacted"* ]]
  sub_pre
  assert_silent
  compact_sub
  sub_pre
  assert_injected "GOAL: ship the thing"
}

@test "a main-session compaction does not make a subagent inject" {
  sub_start
  compact_main
  sub_pre
  assert_silent
}

@test "a transcript_path that is already the subagent file works" {
  fire SubagentStart "$(jq -c --arg t "${SUB_FILE}" '.transcript_path = $t' <<<"$(sub_in SubagentStart "${AGENT}")")"
  compact_sub
  fire PreToolUse "$(jq -c --arg t "${SUB_FILE}" '.transcript_path = $t' <<<"$(sub_in PreToolUse "${AGENT}")")"
  assert_injected "compacted"
}

@test "a subagent PreToolUse with no saved state starts its notes once" {
  sub_pre
  assert_injected "${SUB_NOTES}"
  sub_pre
  assert_silent
}

@test "a missing subagent transcript still injects on the first call and stays silent after" {
  rm "${SUB_FILE}"
  sub_pre
  assert_injected "${SUB_NOTES}"
  sub_pre
  assert_silent
}

@test "agents keep separate state" {
  sub_start
  sub_start other-agent
  assert_injected "agent-other-agent.md"
  sub_pre
  assert_silent
}

@test "parallel subagent calls after one compaction inject exactly once" {
  sub_start
  printf 'GOAL: ship the thing\n' >"${SUB_NOTES}"
  compact_sub
  payload="$(sub_in PreToolUse "${AGENT}")"
  for i in 1 2 3 4 5 6; do
    bash "${SCRIPT}" PreToolUse <<<"${payload}" >"${TMP}/out.${i}" &
  done
  wait
  [ "$(cat "${TMP}"/out.* | grep -c additionalContext)" -eq 1 ]
}

@test "parallel first subagent calls inject exactly once" {
  payload="$(sub_in PreToolUse "${AGENT}")"
  for i in 1 2 3 4 5 6; do
    bash "${SCRIPT}" PreToolUse <<<"${payload}" >"${TMP}/out.${i}" &
  done
  wait
  [ "$(cat "${TMP}"/out.* | grep -c additionalContext)" -eq 1 ]
}

# --- Notes reminder -----------------------------------------------------------

tool_calls() {
  local i
  for ((i = 0; i < $1; i++)); do
    printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_01","name":"Bash","input":{"command":"ls"}}]},"type":"assistant"}' >>"${SUB_FILE}"
    printf '%s\n' '{"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01","content":"ok"}]},"type":"user"}' >>"${SUB_FILE}"
  done
}

@test "a subagent with no notes is reminded at the default threshold of 10 tool calls" {
  sub_start
  tool_calls 10
  sub_pre
  [ "$(event_name)" = "PreToolUse" ]
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"10 tool calls"* ]]
  [[ "$(context)" == *"no progress notes"* ]]
  [[ "$(context)" == *"more than one step"* ]]
}

@test "no reminder below the threshold" {
  sub_start
  tool_calls 9
  sub_pre
  assert_silent
}

@test "no reminder when the notes already exist" {
  sub_start
  printf 'GOAL: ship the thing\n' >"${SUB_NOTES}"
  tool_calls 25
  sub_pre
  assert_silent
}

@test "notes written then deleted stay silent" {
  sub_start
  tool_calls 3
  printf 'GOAL: ship the thing\n' >"${SUB_NOTES}"
  sub_pre
  assert_silent
  rm -f "${SUB_NOTES}"
  tool_calls 20
  sub_pre
  assert_silent
  [ ! -e "${SUB_NOTES}" ]
}

@test "empty notes still count as missing" {
  sub_start
  : >"${SUB_NOTES}"
  tool_calls 12
  sub_pre
  assert_injected "${SUB_NOTES}"
}

@test "the reminder fires once per subagent" {
  sub_start
  tool_calls 10
  sub_pre
  assert_injected "${SUB_NOTES}"
  [ -e "${DIR}/agent-${AGENT}.claim-nudge" ]
  tool_calls 5
  sub_pre
  assert_silent
}

@test "parallel calls past the threshold remind exactly once" {
  sub_start
  tool_calls 12
  payload="$(sub_in PreToolUse "${AGENT}")"
  for i in 1 2 3 4 5 6; do
    bash "${SCRIPT}" PreToolUse <<<"${payload}" >"${TMP}/out.${i}" &
  done
  wait
  [ "$(cat "${TMP}"/out.* | grep -c additionalContext)" -eq 1 ]
}

@test "the threshold comes from the plugin default progress.json" {
  with_plugin_config '{"notesAgents":["builder"],"nudgeAfterToolCalls":3}'
  sub_start
  tool_calls 2
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"3 tool calls"* ]]
}

@test "a subagent that is not opted in is never reminded" {
  sub_pre 5 general-purpose
  assert_silent
  tool_calls 30
  sub_pre "${AGENT}" general-purpose
  assert_silent
  no_files
}

@test "the main session is never reminded" {
  start startup
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t","name":"Bash","input":{}}]}}' >>"${SESSION_FILE}"
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t","name":"Bash","input":{}}]}}' >>"${SESSION_FILE}"
  done
  main_pre
  assert_silent
}

@test "tool_use text inside message content does not count as a tool call" {
  sub_start
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    printf '%s\n' '{"type":"user","message":{"content":"grep \"type\":\"tool_use\" in the log"}}' >>"${SUB_FILE}"
  done
  sub_pre
  assert_silent
}

@test "the compaction reminder still fires and the notes reminder waits for the next call" {
  sub_start
  tool_calls 12
  compact_sub
  sub_pre
  assert_injected "context was compacted"
  sub_pre
  assert_injected "tool calls"
  sub_pre
  assert_silent
}

@test "the first call without saved state injects the start message, not the reminder" {
  tool_calls 12
  sub_pre
  assert_injected "Your progress notes file is"
  [[ "$(context)" != *"tool calls"* ]]
}

@test "SubagentStop drops the reminder claim so a resumed agent can be reminded again" {
  sub_start
  tool_calls 10
  sub_pre
  sub_stop
  [ ! -e "${DIR}/agent-${AGENT}.claim-nudge" ]
}

# --- Context warning ------------------------------------------------------------

# Appends an assistant entry whose three input counts sum to $2 tokens; $3 is its isSidechain
usage_line() {
  local file=$1 total=$2 side=$3
  jq -nc --argjson t "${total}" --argjson side "${side}" \
    '{type: "assistant", isSidechain: $side, message: {model: "claude-opus-5-5", role: "assistant",
      content: [{type: "tool_use", id: "toolu_01", name: "Bash", input: {}}],
      usage: {input_tokens: 2, cache_creation_input_tokens: 1000, cache_read_input_tokens: ($t - 1002), output_tokens: 50}}}' >>"${file}"
}

main_usage() { usage_line "${SESSION_FILE}" "$1" false; }
# A subagent's own transcript marks every entry as side-chain
sub_usage() { usage_line "${SUB_FILE}" "$1" true; }

@test "the main session is warned at 90% of the default 200000 compaction point" {
  start startup
  main_usage 180000
  main_pre
  [ "$(event_name)" = "PreToolUse" ]
  assert_injected "180000 tokens"
  [[ "$(context)" == *"90%"* ]]
  [[ "$(context)" == *"200000"* ]]
  [[ "$(context)" == *"${MAIN_NOTES}"* ]]
  [[ "$(context)" == *"before"*"compact"* ]]
  [[ "$(context)" == *"more than one step"* ]]
}

@test "no context warning below 90%" {
  start startup
  main_usage 179999
  main_pre
  assert_silent
}

@test "each warning level fires once" {
  start startup
  main_usage 181000
  main_pre
  assert_injected "90%"
  main_usage 185000
  main_pre
  assert_silent
  main_usage 190000
  main_pre
  assert_injected "95%"
  main_usage 195000
  main_pre
  assert_silent
}

@test "a jump past both levels warns once" {
  start startup
  main_usage 197000
  main_pre
  assert_injected "98%"
  main_usage 198000
  main_pre
  assert_silent
}

@test "the size sums input, cache creation and cache read tokens" {
  start startup
  printf '%s\n' '{"type":"assistant","message":{"usage":{"input_tokens":100000,"cache_creation_input_tokens":40000,"cache_read_input_tokens":40000,"output_tokens":9}}}' >>"${SESSION_FILE}"
  main_pre
  assert_injected "180000 tokens"
}

@test "only the latest assistant entry counts" {
  start startup
  main_usage 199000
  main_usage 50000
  printf '%s\n' '{"type":"user","message":{"content":[{"type":"tool_result","content":"\"usage\": lots"}]}}' >>"${SESSION_FILE}"
  main_pre
  assert_silent
}

@test "entries that are not real assistant replies are ignored" {
  start startup
  main_usage 50000
  printf '%s\n' '{"type":"progress","data":{"message":{"type":"assistant","message":{"usage":{"input_tokens":190000}}}}}' \
    '{"type":"assistant","isSidechain":true,"message":{"usage":{"input_tokens":190000}}}' \
    '{"type":"assistant","message":{"model":"<synthetic>","usage":{"input_tokens":0,"cache_read_input_tokens":0}}}' >>"${SESSION_FILE}"
  main_pre
  assert_silent
  main_usage 185000
  printf '%s\n' '{"type":"assistant","message":{"model":"<synthetic>","usage":{"input_tokens":0,"cache_read_input_tokens":0}}}' >>"${SESSION_FILE}"
  main_pre
  assert_injected "185000 tokens"
}

@test "missing or malformed usage stays silent" {
  start startup
  for bad in '{"type":"assistant","message":{"usage":{"input_tokens":"190000"}}}' \
    '{"type":"assistant","message":{"usage":"190000"}}' \
    '{"type":"assistant","message":{"usage":{"input_tokens":-5,"cache_read_input_tokens":190000}}}' \
    '{"type":"assistant","message":{"content":"no usage here"}}' \
    'not json "usage"'; do
    printf '%s\n' "${bad}" >>"${SESSION_FILE}"
    main_pre
    assert_silent
  done
}

@test "a high size from before a compaction does not warn after it" {
  start startup
  main_usage 199000
  compact_main
  main_pre
  assert_injected "context was compacted"
  main_pre
  assert_silent
}

@test "a compaction resets the warning levels" {
  start startup
  main_usage 185000
  main_pre
  assert_injected "92%"
  compact_main
  main_usage 20000
  main_pre
  assert_injected "context was compacted"
  main_usage 182000
  main_pre
  assert_injected "91%"
}

@test "the warning levels are reset even when the hook dies right after saving the compaction count" {
  start startup
  main_usage 185000
  main_pre
  assert_injected "92%"
  compact_main
  main_usage 20000
  mkdir -p "${TMP}/killmv"
  cat >"${TMP}/killmv/mv" <<'STUB'
#!/bin/bash
command -p mv "$@"
case "$*" in *.state) kill -KILL "$PPID" ;; esac
STUB
  chmod +x "${TMP}/killmv/mv"
  run --separate-stderr env PATH="${TMP}/killmv:${PATH}" bash "${SCRIPT}" PreToolUse <<<"$(main_in PreToolUse)"
  main_usage 182000
  main_pre
  assert_injected "91%"
}

@test "SessionStart resume resets the warning levels" {
  start startup
  main_usage 185000
  main_pre
  assert_injected "92%"
  start resume
  main_pre
  assert_injected "92%"
}

@test "an unsorted warnAtPercent with duplicates warns once per level" {
  with_repo_config '{"progress":{"warnAtPercent":[95,90,90]}}'
  start startup
  main_usage 182000
  main_pre
  assert_injected "91%"
  main_pre
  assert_silent
  main_usage 192000
  main_pre
  assert_injected "96%"
  main_pre
  assert_silent
}

@test "the warning names the notes path but leaves out the notes text" {
  mkdir -p "${DIR}"
  printf 'GOAL: keep me out\n' >"${MAIN_NOTES}"
  start resume
  main_usage 185000
  main_pre
  assert_injected "${MAIN_NOTES}"
  [[ "$(context)" != *"GOAL: keep me out"* ]]
}

@test "an opted-in subagent is warned from its own transcript" {
  sub_start
  main_usage 199000
  sub_pre
  assert_silent
  sub_usage 185000
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"92%"* ]]
}

@test "a subagent that is not opted in is never warned" {
  sub_usage 199000
  sub_pre "${AGENT}" general-purpose
  assert_silent
  no_files
}

@test "the context warning comes before the notes reminder" {
  sub_start
  tool_calls 12
  sub_usage 185000
  sub_pre
  assert_injected "92%"
  sub_pre
  assert_injected "no progress notes"
}

@test "parallel calls past a level warn exactly once" {
  start startup
  main_usage 185000
  payload="$(main_in PreToolUse)"
  for i in 1 2 3 4 5 6; do
    bash "${SCRIPT}" PreToolUse <<<"${payload}" >"${TMP}/out.${i}" &
  done
  wait
  [ "$(cat "${TMP}"/out.* | grep -c additionalContext)" -eq 1 ]
}

@test "a repo compactAtTokens and warnAtPercent replace the defaults" {
  with_repo_config '{"progress":{"compactAtTokens":100000,"warnAtPercent":[50]}}'
  start startup
  main_usage 49999
  main_pre
  assert_silent
  main_usage 50000
  main_pre
  assert_injected "50% of the 100000"
  main_usage 99000
  main_pre
  assert_silent
}

@test "an empty warnAtPercent turns the warning off" {
  with_repo_config '{"progress":{"warnAtPercent":[]}}'
  start startup
  main_usage 199000
  main_pre
  assert_silent
}

@test "bad compactAtTokens or warnAtPercent values fall back to the defaults" {
  for bad in '"compactAtTokens":"100000"' '"compactAtTokens":0' '"compactAtTokens":1.5' '"compactAtTokens":-1' \
    '"warnAtPercent":90' '"warnAtPercent":[0]' '"warnAtPercent":[101]' '"warnAtPercent":["50"]' \
    '"warnAtPercent":[50.5]' '"warnAtPercent":[[50]]' '"warnAtPercent":null'; do
    rm -rf "${DIR}"
    : >"${SESSION_FILE}"
    with_repo_config "{\"progress\":{${bad}}}"
    start startup
    main_usage 120000
    main_pre
    assert_silent
    main_usage 180000
    main_pre
    assert_injected "90% of the 200000"
  done
}

@test "the plugin default supplies compactAtTokens and warnAtPercent" {
  with_plugin_config '{"compactAtTokens":2000,"warnAtPercent":[80]}'
  start startup
  main_usage 1500
  main_pre
  assert_silent
  main_usage 1700
  main_pre
  assert_injected "85% of the 2000"
  [[ "$(context)" == *"1700 tokens"* ]]
}

# --- Claim cleanup --------------------------------------------------------------

@test "after compaction n only that key's claim-n remains" {
  sub_start
  for i in 1 2 3; do
    compact_sub
    sub_pre
    [ -e "${DIR}/agent-${AGENT}.claim-${i}" ]
  done
  [ ! -e "${DIR}/agent-${AGENT}.claim-1" ]
  [ ! -e "${DIR}/agent-${AGENT}.claim-2" ]
  [ "$(ls "${DIR}" | grep -c "^agent-${AGENT}\.claim-")" -eq 1 ]
}

@test "main session compactions also keep only the latest numbered claim" {
  start startup
  for i in 1 2 3; do
    compact_main
    main_pre
  done
  [ "$(ls "${DIR}" | grep -c "^${SID}\.claim-")" -eq 1 ]
  [ -e "${DIR}/${SID}.claim-3" ]
}

@test "the compaction sweep keeps an existing claim-nudge" {
  sub_start
  printf 'x\n' >"${SUB_NOTES}"
  : >"${DIR}/agent-${AGENT}.claim-nudge"
  compact_sub
  sub_pre
  compact_sub
  sub_pre
  [ -e "${DIR}/agent-${AGENT}.claim-nudge" ]
  [ -e "${DIR}/agent-${AGENT}.claim-2" ]
  [ ! -e "${DIR}/agent-${AGENT}.claim-1" ]
}

@test "the compaction sweep leaves other keys' claims alone" {
  sub_start
  sub_start other99
  : >"${DIR}/agent-other99.claim-1"
  : >"${DIR}/${SID}.claim-1"
  compact_sub
  sub_pre
  compact_sub
  sub_pre
  [ ! -e "${DIR}/agent-${AGENT}.claim-1" ]
  [ -e "${DIR}/agent-other99.claim-1" ]
  [ -e "${DIR}/${SID}.claim-1" ]
}

@test "the compaction sweep leaves claims for higher counts alone" {
  sub_start
  : >"${DIR}/agent-${AGENT}.claim-5"
  compact_sub
  sub_pre
  [ -e "${DIR}/agent-${AGENT}.claim-5" ]
}

# --- SubagentStop ------------------------------------------------------------

@test "SubagentStop removes that agent's state and claims and keeps its notes" {
  sub_start
  compact_sub
  sub_pre
  printf 'GOAL: keep me\n' >"${SUB_NOTES}"
  [ -e "${DIR}/agent-${AGENT}.state" ]
  compgen -G "${DIR}/agent-${AGENT}.claim-*" >/dev/null
  sub_stop
  assert_silent
  [ ! -e "${DIR}/agent-${AGENT}.state" ]
  if compgen -G "${DIR}/agent-${AGENT}.claim-*" >/dev/null; then return 1; fi
  [ "$(cat "${SUB_NOTES}")" = "GOAL: keep me" ]
}

@test "SubagentStop leaves other agents' and the main session's files alone" {
  start startup
  sub_start
  sub_start other-agent
  sub_start "${AGENT}-2"
  sub_stop
  [ -e "${DIR}/agent-other-agent.state" ]
  [ -e "${DIR}/agent-${AGENT}-2.state" ]
  [ -e "${DIR}/${SID}.state" ]
}

@test "SubagentStop for an internal helper call with an empty agent_type is a silent no-op" {
  sub_start
  sub_stop "${AGENT}" ""
  assert_silent
  [ -e "${DIR}/agent-${AGENT}.state" ]
}

@test "SubagentStop does not create the notes folder" {
  sub_stop
  [ ! -e "${DIR}" ]
}

@test "SubagentStop does not follow a symlinked state or claim file" {
  mkdir -p "${DIR}"
  printf 'x\n' >"${TMP}/target"
  ln -s "${TMP}/target" "${DIR}/agent-${AGENT}.state"
  ln -s "${TMP}/target" "${DIR}/agent-${AGENT}.claim-0"
  sub_stop
  [ -L "${DIR}/agent-${AGENT}.state" ]
  [ -L "${DIR}/agent-${AGENT}.claim-0" ]
  [ "$(cat "${TMP}/target")" = "x" ]
}

# --- cap ---------------------------------------------------------------------

@test "SessionStart output is capped at 9500 characters and the cut is flagged" {
  mkdir -p "${DIR}"
  head -c 20000 /dev/zero | tr '\0' 'n' >"${MAIN_NOTES}"
  start resume
  [ "$(context | wc -c)" -le 9501 ]
  [ "${#output}" -lt 10000 ]
  [[ "$(context)" == *"truncated"* ]]
  [[ "$(context)" == *"more than one step"* ]]
}

@test "compaction output is capped at 9500 characters and the cut is flagged" {
  start startup
  head -c 20000 /dev/zero | tr '\0' 'n' >"${MAIN_NOTES}"
  compact_main
  main_pre
  [ "$(context | wc -c)" -le 9501 ]
  [[ "$(context)" == *"truncated"* ]]
}

@test "subagent output is capped at 9500 characters and the cut is flagged" {
  mkdir -p "${DIR}"
  head -c 20000 /dev/zero | tr '\0' 'n' >"${SUB_NOTES}"
  sub_start
  [ "$(context | wc -c)" -le 9501 ]
  [[ "$(context)" == *"truncated"* ]]
}

@test "notes just under the cap are not flagged as cut" {
  mkdir -p "${DIR}"
  printf 'short notes\n' >"${MAIN_NOTES}"
  start startup
  [[ "$(context)" != *"truncated"* ]]
}

@test "multibyte notes cut at the cap still produce valid JSON" {
  mkdir -p "${DIR}"
  for _ in $(seq 1 5000); do printf 'é€é€é€é€'; done >"${MAIN_NOTES}"
  start resume
  jq -e . >/dev/null <<<"${output}"
  [[ "$(context)" == *"truncated"* ]]
}

# --- rule text ---------------------------------------------------------------

@test "every kind of injection carries the full rule" {
  mkdir -p "${DIR}"
  printf 'N\n' >"${MAIN_NOTES}"
  start startup
  first=$(context)
  compact_main
  main_pre
  second=$(context)
  sub_start
  third=$(context)
  for text in "$first" "$second" "$third"; do
    [[ "${text}" == *"more than one step"* ]]
    [[ "${text}" == *"under 100 lines"* ]]
    [[ "${text}" == *"commit SHAs"* ]]
    [[ "${text}" == *"exact next step"* ]]
    [[ "${text}" == *"dead ends"* ]]
    [[ "${text}" == *"Delete the file when"* ]]
    [[ "${text}" == *"keep it when"* ]]
    [[ "${text}" == *"earlier notes file"* ]]
    [[ "${text}" == *"ls -t"* ]]
  done
}

# --- safety ------------------------------------------------------------------

@test "a session_id that is not a plain identifier is silent and writes nothing" {
  for bad in "../x" "a/b" "a b" 'a$b' "a.b" ""; do
    SID_SAVE=${SID}
    SID=${bad}
    start startup
    assert_silent
    main_pre
    assert_silent
    main_end
    assert_silent
    SID=${SID_SAVE}
  done
  no_files
}

@test "an agent_id that is not a plain identifier is silent and writes nothing" {
  for bad in "../x" "a/b" "a b" 'a$b' "a.b" "" "agent-" "*"; do
    sub_start "${bad}"
    assert_silent
    if [[ -n "${bad}" ]]; then
      sub_pre "${bad}"
      assert_silent
    fi
    sub_stop "${bad}"
    assert_silent
  done
  no_files
}

@test "a subagent PreToolUse event with no agent_id is handled as the main session" {
  start startup
  main_pre
  assert_silent
}

@test "empty or malformed stdin is silent for every event" {
  for ev in SessionStart SubagentStart PreToolUse SubagentStop SessionEnd; do
    run --separate-stderr bash "${SCRIPT}" "${ev}" <<<''
    assert_silent
    run --separate-stderr bash "${SCRIPT}" "${ev}" <<<'not json'
    assert_silent
    run --separate-stderr bash "${SCRIPT}" "${ev}" <<<'[1,2]'
    assert_silent
  done
  no_files
}

@test "an unknown or missing event is silent" {
  run --separate-stderr bash "${SCRIPT}" Nonsense <<<"$(main_in SessionStart startup)"
  assert_silent
  run --separate-stderr bash "${SCRIPT}" <<<"$(main_in SessionStart startup)"
  assert_silent
  no_files
}

@test "without CLAUDE_PROJECT_DIR every event is silent" {
  unset CLAUDE_PROJECT_DIR
  start startup
  assert_silent
  sub_start
  assert_silent
  main_pre
  assert_silent
}

@test "without jq the script is silent and exits 0" {
  mkdir -p "${TMP}/nojq"
  for tool in cat grep head wc rm mkdir git dirname tr printf; do
    ln -s "$(command -v "${tool}")" "${TMP}/nojq/${tool}"
  done
  run --separate-stderr env PATH="${TMP}/nojq" "$(command -v bash)" "${SCRIPT}" SessionStart <<<"$(main_in SessionStart startup)"
  assert_silent
  no_files
}

@test "a symlinked notes file is silent and not followed" {
  mkdir -p "${DIR}"
  printf 'SECRET\n' >"${TMP}/target.md"
  ln -s "${TMP}/target.md" "${SUB_NOTES}"
  sub_start
  assert_silent
  ln -s "${TMP}/target.md" "${MAIN_NOTES}"
  start startup
  assert_silent
}

@test "a symlinked state file is silent and not written through" {
  mkdir -p "${DIR}"
  printf 'x\n' >"${TMP}/target.state"
  ln -s "${TMP}/target.state" "${DIR}/agent-${AGENT}.state"
  sub_start
  assert_silent
  ln -s "${TMP}/target.state" "${DIR}/${SID}.state"
  start startup
  assert_silent
  [ "$(cat "${TMP}/target.state")" = "x" ]
}

@test "a symlinked .agent-progress folder is silent and nothing is written through it" {
  mkdir "${TMP}/elsewhere"
  ln -s "${TMP}/elsewhere" "${DIR}"
  start startup
  assert_silent
  sub_start
  assert_silent
  main_pre
  assert_silent
  sub_stop
  main_end
  [ -z "$(ls -A "${TMP}/elsewhere")" ]
}

@test "a state file that points the notes path outside the folder is not followed" {
  start startup
  printf 'SECRET\n' >"${TMP}/secret.md"
  printf '0\n%s\n' "${TMP}/secret.md" >"${DIR}/${SID}.state"
  rm -f "${DIR}/${SID}".claim-*
  compact_main
  main_pre
  [[ "$(context)" != *"SECRET"* ]]
}

@test "the hook payload is parsed with one jq call" {
  mkdir -p "${TMP}/spy"
  printf '#!/bin/bash\necho call >>"%s/jq.log"\nexec %s "$@"\n' "${TMP}" "$(command -v jq)" >"${TMP}/spy/jq"
  chmod +x "${TMP}/spy/jq"
  run --separate-stderr env PATH="${TMP}/spy:${PATH}" bash "${SCRIPT}" SessionStart <<<"$(main_in SessionStart startup)"
  [ "${status}" -eq 0 ]
  [ "$(wc -l <"${TMP}/jq.log")" -le 2 ]
  [ "$(context)" != "" ]
}

config_jq_calls() {
  mkdir -p "${TMP}/spy"
  printf '#!/bin/bash\necho "$*" >>"%s/jq.log"\nexec %s "$@"\n' "${TMP}" "$(command -v jq)" >"${TMP}/spy/jq"
  chmod +x "${TMP}/spy/jq"
  : >"${TMP}/jq.log"
}

config_reads() {
  grep -c -e "--arg want" "${TMP}/jq.log" || true
}

@test "the config is loaded once per subagent invocation, in one jq call" {
  config_jq_calls
  tool_calls 12
  run --separate-stderr env PATH="${TMP}/spy:${PATH}" bash "${SCRIPT}" SubagentStart <<<"$(sub_in SubagentStart "${AGENT}")"
  [ "$(config_reads)" -eq 1 ]
  : >"${TMP}/jq.log"
  run --separate-stderr env PATH="${TMP}/spy:${PATH}" bash "${SCRIPT}" PreToolUse <<<"$(sub_in PreToolUse "${AGENT}")"
  assert_injected "${SUB_NOTES}"
  [ "$(config_reads)" -eq 1 ]
}

@test "the main session reads the config only on PreToolUse, once" {
  config_jq_calls
  run --separate-stderr env PATH="${TMP}/spy:${PATH}" bash "${SCRIPT}" SessionStart <<<"$(main_in SessionStart startup)"
  [ "$(config_reads)" -eq 0 ]
  run --separate-stderr env PATH="${TMP}/spy:${PATH}" bash "${SCRIPT}" PreToolUse <<<"$(main_in PreToolUse)"
  [ "$(config_reads)" -eq 1 ]
  run --separate-stderr env PATH="${TMP}/spy:${PATH}" bash "${SCRIPT}" SessionEnd <<<"$(main_in SessionEnd)"
  [ "$(config_reads)" -eq 1 ]
}

@test "payload fields stay in place when earlier ones are empty" {
  mkdir -p "${TMP}/wt-parent"
  git -C "${CLAUDE_PROJECT_DIR}" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git -C "${CLAUDE_PROJECT_DIR}" worktree add -q "${TMP}/wt-parent/wt"
  CWD="${TMP}/wt-parent/wt"
  start startup
  assert_injected "${TMP}/wt-parent/wt/.agent-progress/${SID}.md"
}

@test "a state file that is not a regular file is silent and never read" {
  mkdir -p "${DIR}"
  mkfifo "${DIR}/${SID}.state"
  run --separate-stderr timeout 5 bash "${SCRIPT}" PreToolUse <<<"$(main_in PreToolUse)"
  assert_silent
  mkfifo "${DIR}/agent-${AGENT}.state"
  run --separate-stderr timeout 5 bash "${SCRIPT}" PreToolUse <<<"$(sub_in PreToolUse "${AGENT}")"
  assert_silent
}

@test "a claim file that is not a regular file does not stall the hook" {
  mkdir -p "${DIR}"
  mkfifo "${DIR}/${SID}.claim-0"
  run --separate-stderr timeout 5 bash "${SCRIPT}" PreToolUse <<<"$(main_in PreToolUse)"
  assert_silent
}

@test "saving state leaves only the state file and no temporary files" {
  start startup
  sub_start
  names=$(ls -A "${DIR}" | sort | tr '\n' ' ')
  [ "${names}" = ".gitignore agent-${AGENT}.state ${SID}.state " ]
}

@test "notes that are not a plain regular file are not read" {
  mkdir -p "${DIR}"
  printf 'SECRET\n' >"${TMP}/target.md"
  ln "${TMP}/target.md" "${MAIN_NOTES}"
  start startup
  [[ "$(context)" != *"SECRET"* ]]
  [[ "$(context)" == *"none written yet"* ]]
  ln "${TMP}/target.md" "${SUB_NOTES}"
  sub_start
  [[ "$(context)" != *"SECRET"* ]]
  [[ "$(context)" == *"none written yet"* ]]
  rm -f "${MAIN_NOTES}" "${SUB_NOTES}"
  mkdir "${MAIN_NOTES}" "${SUB_NOTES}"
  start startup
  [[ "$(context)" == *"none written yet"* ]]
  sub_start
  [[ "$(context)" == *"none written yet"* ]]
}

@test "creates the notes folder when it is missing" {
  [ ! -e "${DIR}" ]
  sub_start
  assert_injected "${SUB_NOTES}"
  [ -d "${DIR}" ]
}
