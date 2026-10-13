#!/bin/bash
# Progress notes for the main session and opted-in subagents. Usage: progress.sh <hook event name>
# Bad input or any error means no output and exit 0, so no tool call or session start is blocked.
set -u
export LC_ALL=C
exec 2>/dev/null

event=${1:-}
# Claude Code caps hook output at 10,000 characters
CAP=9500

command -v jq >/dev/null || exit 0
input=$(cat) || exit 0
project=${CLAUDE_PROJECT_DIR:-}
[[ -n "$project" ]] || exit 0
plugin_root=${BASH_SOURCE[0]%/*}/..

# The x prefix keeps read from collapsing empty fields; fields holding a tab or newline are dropped
fields=$(jq -r 'if type == "object" then . as $o
  | ["session_id", "agent_id", "agent_type", "transcript_path", "cwd", "source"]
  | map(($o[.] // "") | if type == "string" and test("[\t\n\r]") then "" else tostring end | "x" + .)
  | join("\t") else empty end' <<<"$input")
IFS=$'\t' read -r session_id agent_id agent_type transcript cwd source_ <<<"$fields"
session_id=${session_id#x}
agent_id=${agent_id#x}
agent_type=${agent_type#x}
transcript=${transcript#x}
cwd=${cwd#x}
source_=${source_#x}

case "$event" in
SessionStart | SessionEnd) scope=main ;;
SubagentStart | SubagentStop) scope=sub ;;
PreToolUse) if [[ -n "$agent_id" ]]; then scope=sub; else scope=main; fi ;;
*) exit 0 ;;
esac

in_notes_agents() {
  local want=$1 line
  [[ -n "$want" && -r "$plugin_root/config/notes-agents" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%%#*}
    line=${line#"${line%%[![:space:]]*}"}
    line=${line%"${line##*[![:space:]]}"}
    [[ -n "$line" && "$line" == "$want" ]] && return 0
  done <"$plugin_root/config/notes-agents"
  return 1
}

if [[ "$scope" == main ]]; then
  # The id becomes a file name, so accept only a plain identifier
  [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
  key=$session_id
else
  in_notes_agents "$agent_type" || exit 0
  id=${agent_id#agent-}
  [[ "$id" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
  key=agent-$id
fi

dir="$project/.agent-progress"
state="$dir/$key.state"
[[ ! -L "$dir" && ! -L "$state" ]] || exit 0
[[ ! -e "$state" || -f "$state" ]] || exit 0

drop_claims() {
  local f
  for f in "$dir/$key".claim-*; do
    [[ -f "$f" && ! -L "$f" ]] && rm -f -- "$f"
  done
  return 0
}

# Stop events drop this conversation's bookkeeping, never its notes
if [[ "$event" == SessionEnd || "$event" == SubagentStop ]]; then
  [[ -d "$dir" ]] || exit 0
  rm -f -- "$state"
  drop_claims
  exit 0
fi

if [[ "$event" == SessionStart ]]; then
  # A compaction payload can't say who compacted (anthropics/claude-code#91910): notes come back on the next tool call
  case "$source_" in startup | resume | clear | fork) ;; *) exit 0 ;; esac
fi

make_dir() {
  mkdir -p "$dir" || return 1
  [[ -e "$dir/.gitignore" || -L "$dir/.gitignore" ]] || printf '*\n' >"$dir/.gitignore"
  return 0
}

count_boundaries() {
  local file=$1 n=0
  if [[ -n "$file" && -r "$file" ]]; then
    n=$(grep -cF '"subtype":"compact_boundary"' "$file" || true)
  fi
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  printf '%s' "$n"
  return 0
}

# The hook may carry the session transcript or the subagent's own
transcript_file() {
  if [[ "$scope" == main ]]; then
    [[ "$transcript" == */subagents/agent-*.jsonl ]] || printf '%s' "$transcript"
  elif [[ "$transcript" == */subagents/agent-*.jsonl ]]; then
    printf '%s' "$transcript"
  elif [[ "$transcript" == *.jsonl ]]; then
    printf '%s' "${transcript%.jsonl}/subagents/agent-$id.jsonl"
  fi
  return 0
}

common_dir() {
  local where=$1
  git -C "$where" rev-parse --path-format=absolute --git-common-dir || true
  return 0
}

# cwd follows Claude into a worktree, but also into any other repo it cd's to
resolve_main() {
  local c=${cwd:-$project} root top alt rdir
  [[ "$(common_dir "$c")" == "$(common_dir "$project")" ]] || c=$project
  root=$(git -C "$c" rev-parse --show-toplevel) || return 1
  rdir="$root/.agent-progress"
  file="$rdir/$session_id.md"
  [[ ! -L "$rdir" && ! -L "$file" ]] || return 1
  notes=$file
  # Notes written in the project checkout before cwd moved to another checkout
  if ! usable_notes "$file"; then
    top=$(git -C "$project" rev-parse --show-toplevel || true)
    alt="$top/.agent-progress/$session_id.md"
    if [[ -n "$top" && "$top" != "$root" && ! -L "$top/.agent-progress" && ! -L "$alt" ]] && usable_notes "$alt"; then
      notes=$alt
    fi
  fi
  return 0
}

load_main_paths() {
  { read -r _ && read -r notes && read -r file; } <"$state" || return 1
  [[ "$notes" == */.agent-progress/$session_id.md && "$file" == */.agent-progress/$session_id.md ]] || return 1
  [[ ! -L "$notes" && ! -L "$file" ]]
}

save_state() {
  local seen=$1 tmp
  tmp=$(mktemp "$dir/$key.state.XXXXXX") || return 1
  if [[ "$scope" == main ]]; then
    printf '%s\n%s\n%s\n' "$seen" "$notes" "$file" >"$tmp"
  else
    printf '%s\n' "$seen" >"$tmp"
  fi || { rm -f -- "$tmp"; return 1; }
  mv -f -- "$tmp" "$state" || { rm -f -- "$tmp"; return 1; }
  return 0
}

# Parallel calls race: one claims each count by exclusive create (mkdir is not atomic on virtiofs)
claim() {
  local n=$1
  [[ ! -e "$dir/$key.claim-$n" && ! -L "$dir/$key.claim-$n" ]] || return 1
  (
    set -C
    : >"$dir/$key.claim-$n"
  ) 2>/dev/null
  return $?
}

NUDGE_DEFAULT=10

nudge_threshold() {
  local line n=$NUDGE_DEFAULT
  if [[ -r "$plugin_root/config/notes-nudge-calls" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line=${line%%#*}
      line=${line#"${line%%[![:space:]]*}"}
      line=${line%"${line##*[![:space:]]}"}
      [[ -n "$line" ]] || continue
      [[ "$line" =~ ^[1-9][0-9]{0,5}$ ]] && n=$line
      break
    done <"$plugin_root/config/notes-nudge-calls"
  fi
  printf '%s' "$n"
  return 0
}

count_tool_calls() {
  local file=$1 n=0
  if [[ -n "$file" && -r "$file" ]]; then
    n=$(grep -oF '"type":"tool_use"' "$file" | wc -l || true)
  fi
  n=${n//[^0-9]/}
  printf '%s' "${n:-0}"
  return 0
}

usable_notes() {
  local f=$1
  [[ -f "$f" && ! -L "$f" && -s "$f" ]] || return 1
  [[ -n "$(find "$f" -prune -links 1)" ]] || return 1
  return 0
}

# shellcheck disable=SC2016
RULE='Progress notes rule: keep notes for any task with more than one step; skip one-shot edits and questions. Keep the file under 100 lines. Put the goal and issue on the first line, then what is done with commit SHAs, the exact next step, decisions and why, dead ends, and commands and gotchas that matter. Update it after each commit and before you stop. Delete the file when the task is done; keep it when you are blocked or unfinished. If your brief or the owner names an earlier notes file, read it first and delete it when you finish. To find earlier notes, run `ls -t` on the notes folder and pick the file whose goal matches your task; ignore any file git tracks there. The notes are working memory; git log is the source of truth.'

emit() {
  local ev=$1 ctx="$2"$'\n\n'"$RULE" body="" marker size room
  if usable_notes "$notes"; then
    marker=$'\n\n'"[truncated - read the rest of $notes]"
    size=$(wc -c <"$notes")
    room=$((CAP - ${#ctx} - 2))
    if ((size <= room)); then
      body=$(head -c "$room" "$notes")
    else
      room=$((room - ${#marker}))
      ((room > 0)) || room=0
      body="$(head -c "$room" "$notes")$marker"
    fi
    ctx="$ctx"$'\n\n'"$body"
  fi
  jq -nc --arg ev "$ev" --arg c "$ctx" '{hookSpecificOutput: {hookEventName: $ev, additionalContext: $c}}'
  return 0
}

where() {
  if [[ "$notes" == "$file" ]]; then
    printf '%s' "$notes"
  else
    printf '%s (this checkout would use %s)' "$notes" "$file"
  fi
  return 0
}

start_message() {
  if [[ "$scope" == main ]]; then
    if usable_notes "$notes"; then
      printf 'Progress notes for this session are in %s. Check them against git log before acting on them.' "$(where)"
    else
      printf 'Keep progress notes for this session in %s (none written yet).' "$file"
    fi
  elif usable_notes "$notes"; then
    printf 'Your progress notes already exist in %s. Read them, check them against git log before acting, and keep them current after each commit.' "$notes"
  else
    printf 'Your progress notes file is %s (none written yet). Start it as soon as you start (goal and issue), unless the task is a one-step job the rule lets you skip, and update it after each commit.' "$notes"
  fi
  return 0
}

compact_message() {
  if [[ "$scope" == main ]]; then
    if usable_notes "$notes"; then
      printf 'Your context was compacted. Your progress notes for this session are in %s. Check them against git log before acting on them.' "$(where)"
    else
      printf 'Your context was compacted. Keep progress notes for this session in %s (none written yet).' "$file"
    fi
  elif usable_notes "$notes"; then
    printf 'Your context was compacted. Your progress notes are in %s. Check them against git log before acting on them.' "$notes"
  else
    printf 'Your context was compacted. Your progress notes file is %s (none written yet).' "$notes"
  fi
  return 0
}

notes="" file=""
if [[ "$scope" == sub ]]; then
  notes="$dir/$key.md"
  file=$notes
  [[ ! -L "$notes" ]] || exit 0
fi

count=$(count_boundaries "$(transcript_file)")

notes_nudge() {
  local calls
  [[ "$scope" == sub ]] || return 0
  usable_notes "$notes" && return 0
  [[ ! -e "$dir/$key.claim-nudge" ]] || return 0
  calls=$(count_tool_calls "$(transcript_file)")
  ((calls >= $(nudge_threshold))) || return 0
  claim nudge || return 0
  emit PreToolUse "You are $calls tool calls in and have no progress notes yet. Your notes file is $notes. Start it now (goal and issue) unless the task is a one-step job the rule lets you skip."
  return 0
}

begin() {
  local ev=$1
  make_dir || exit 0
  [[ "$scope" == sub ]] || resolve_main || exit 0
  drop_claims
  save_state "$count" || exit 0
  emit "$ev" "$(start_message)"
  return 0
}

case "$event" in
SessionStart | SubagentStart)
  begin "$event"
  ;;
PreToolUse)
  if [[ ! -e "$state" ]]; then
    make_dir || exit 0
    [[ "$scope" == sub ]] || resolve_main || exit 0
    claim "$count" || exit 0
    save_state "$count" || exit 0
    emit PreToolUse "$(start_message)"
    exit 0
  fi
  seen=$(head -c 20 "$state" | head -n 1)
  seen=${seen//[^0-9]/}
  if ((count > ${seen:-0})); then
    [[ "$scope" == sub ]] || load_main_paths || exit 0
    claim "$count" || exit 0
    save_state "$count" || exit 0
    emit PreToolUse "$(compact_message)"
    exit 0
  fi
  notes_nudge
  ;;
*) ;;
esac
exit 0
