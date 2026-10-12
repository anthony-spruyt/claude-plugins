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

field() {
  local key=$1
  jq -r --arg k "$key" 'if type == "object" then (.[$k] // empty | tostring) else empty end' <<<"$input"
  return 0
}

session_id=$(field session_id)
agent_id=$(field agent_id)
agent_type=$(field agent_type)
transcript=$(field transcript_path)
cwd=$(field cwd)
source_=$(field source)

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

# The old scripts own a scope until their file is gone
if [[ "$scope" == main ]]; then
  [[ ! -f "$project/.claude/session-progress.sh" ]] || exit 0
  # The id becomes a file name, so accept only a plain identifier
  [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
  key=$session_id
else
  [[ ! -f "$project/.claude/scripts/builder-progress.sh" ]] || exit 0
  in_notes_agents "$agent_type" || exit 0
  id=${agent_id#agent-}
  [[ "$id" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
  key=agent-$id
fi

dir="$project/.agent-progress"
state="$dir/$key.state"
[[ ! -L "$dir" && ! -L "$state" ]] || exit 0

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
  if [[ ! -s "$file" ]]; then
    top=$(git -C "$project" rev-parse --show-toplevel || true)
    alt="$top/.agent-progress/$session_id.md"
    if [[ -n "$top" && "$top" != "$root" && ! -L "$top/.agent-progress" && ! -L "$alt" && -s "$alt" ]]; then
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
  local seen=$1
  if [[ "$scope" == main ]]; then
    printf '%s\n%s\n%s\n' "$seen" "$notes" "$file" >"$state"
  else
    printf '%s\n' "$seen" >"$state"
  fi
  return $?
}

# Parallel calls race: one claims each count by exclusive create (mkdir is not atomic on virtiofs)
claim() {
  local n=$1
  (
    set -C
    : >"$dir/$key.claim-$n"
  ) 2>/dev/null
  return $?
}

# shellcheck disable=SC2016
RULE='Progress notes rule: keep notes for any task with more than one step; skip one-shot edits and questions. Keep the file under 100 lines. Put the goal and issue on the first line, then what is done with commit SHAs, the exact next step, decisions and why, dead ends, and commands and gotchas that matter. Update it after each commit and before you stop. Delete the file when the task is done; keep it when you are blocked or unfinished. If your brief or the owner names an earlier notes file, read it first and delete it when you finish. To find earlier notes, run `ls -t` on the notes folder and pick the file whose goal matches your task; ignore any file git tracks there. The notes are working memory; git log is the source of truth.'

# header, then the rule, then the notes cut so the whole stays under CAP
emit() {
  local ev=$1 ctx="$2"$'\n\n'"$RULE" body="" marker size room
  if [[ -f "$notes" && -s "$notes" ]]; then
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
    if [[ -s "$notes" ]]; then
      printf 'Progress notes for this session are in %s. Check them against git log before acting on them.' "$(where)"
    else
      printf 'Keep progress notes for this session in %s (none written yet).' "$file"
    fi
  elif [[ -s "$notes" ]]; then
    printf 'Your progress notes already exist in %s. Read them, check them against git log before acting, and keep them current after each commit.' "$notes"
  else
    printf 'Your progress notes file is %s (none written yet). Notes are required: write it as soon as workspace.sh prints your path (goal and issue, workspace path), then update it after each commit.' "$notes"
  fi
  return 0
}

compact_message() {
  if [[ "$scope" == main ]]; then
    if [[ -s "$notes" ]]; then
      printf 'Your context was compacted. Your progress notes for this session are in %s. Check them against git log before acting on them.' "$(where)"
    else
      printf 'Your context was compacted. Keep progress notes for this session in %s (none written yet).' "$file"
    fi
  elif [[ -s "$notes" ]]; then
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

# First sight of a conversation: session start, subagent start, or a tool call with no saved state
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
  ((count > ${seen:-0})) || exit 0
  [[ "$scope" == sub ]] || load_main_paths || exit 0
  claim "$count" || exit 0
  save_state "$count" || exit 0
  emit PreToolUse "$(compact_message)"
  ;;
*) ;;
esac
exit 0
