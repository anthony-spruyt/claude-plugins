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

@test "the shipped notes-agents list holds exactly builder" {
  [ "$(grep -v '^[[:space:]]*\(#\|$\)' "${PLUGIN}/config/notes-agents")" = "builder" ]
}

@test "listing another agent type in config/notes-agents opts it in; comments and blank lines are ignored" {
  mkdir -p "${TMP}/plugin"
  cp -r "${PLUGIN}/scripts" "${PLUGIN}/config" "${TMP}/plugin/"
  printf '# who keeps notes\n\nbuilder\nagent-kit:reviewer\n' >"${TMP}/plugin/config/notes-agents"
  SCRIPT_TO_RUN="${TMP}/plugin/scripts/progress.sh"
  sub_start "${AGENT}" agent-kit:reviewer
  assert_injected "${SUB_NOTES}"
  sub_start "${AGENT}" "# who keeps notes"
  assert_silent
  sub_start "${AGENT}" general-purpose
  assert_silent
}

@test "a missing config/notes-agents opts nobody in" {
  mkdir -p "${TMP}/plugin"
  cp -r "${PLUGIN}/scripts" "${TMP}/plugin/"
  SCRIPT_TO_RUN="${TMP}/plugin/scripts/progress.sh"
  sub_start
  assert_silent
  no_files
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

with_nudge_config() {
  mkdir -p "${TMP}/plugin"
  cp -r "${PLUGIN}/scripts" "${PLUGIN}/config" "${TMP}/plugin/"
  printf '%b' "$1" >"${TMP}/plugin/config/notes-nudge-calls"
  SCRIPT_TO_RUN="${TMP}/plugin/scripts/progress.sh"
}

@test "the shipped notes-nudge-calls config holds exactly one integer" {
  [ "$(grep -v '^[[:space:]]*\(#\|$\)' "${PLUGIN}/config/notes-nudge-calls")" = "10" ]
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

@test "the threshold comes from config/notes-nudge-calls; comments and blank lines are ignored" {
  with_nudge_config '# calls before the reminder\n\n3\n'
  sub_start
  tool_calls 2
  sub_pre
  assert_silent
  tool_calls 1
  sub_pre
  assert_injected "${SUB_NOTES}"
  [[ "$(context)" == *"3 tool calls"* ]]
}

@test "a bad or missing threshold falls back to 10" {
  for bad in 'abc\n' '0\n' '-4\n' '3.5\n' '99999999999999999999\n' '' '# only a comment\n'; do
    rm -rf "${DIR}"
    : >"${SUB_FILE}"
    with_nudge_config "${bad}"
    sub_start
    tool_calls 9
    sub_pre
    assert_silent
    tool_calls 1
    sub_pre
    assert_injected "${SUB_NOTES}"
  done
  rm -rf "${DIR}" "${TMP}/plugin/config/notes-nudge-calls"
  : >"${SUB_FILE}"
  sub_start
  tool_calls 10
  sub_pre
  assert_injected "${SUB_NOTES}"
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
