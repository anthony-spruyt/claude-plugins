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

NUDGE_DEFAULT=10
COMPACT_DEFAULT=200000
WARN_DEFAULT="90 95"
CONFIG_CAP=65536

read_config() {
  local f=$1 strict=${2:-}
  [[ -f "$f" ]] || return 0
  [[ -z "$strict" || (! -L "$f" && ! -L "${f%/*}") ]] || return 0
  head -c "$CONFIG_CAP" "$f" || true
  return 0
}

# Sets the globals cfg_opted, cfg_calls, cfg_compact and cfg_warn (levels, ascending, space separated)
load_config() {
  local want=$1 def rep out
  cfg_opted=false cfg_calls=$NUDGE_DEFAULT cfg_compact=$COMPACT_DEFAULT cfg_warn=$WARN_DEFAULT
  def=$(read_config "$plugin_root/config/progress.json")
  rep=$(read_config "$project/.claude/agent-kit.json" strict)
  out=$(jq -nr --arg want "$want" --arg def "$def" --arg rep "$rep" --argjson dn "$NUDGE_DEFAULT" \
    --argjson dc "$COMPACT_DEFAULT" --arg dw "$WARN_DEFAULT" '
    def obj: if type == "object" then . else {} end;
    def int(lo; hi): type == "number" and . == floor and . >= lo and . <= hi;
    def agents: type == "array" and all(.[]; type == "string" and length > 0);
    def levels: type == "array" and all(.[]; int(1; 100));
    ($def | try fromjson catch null | obj) as $d
    | ($rep | try fromjson catch null | obj | .progress | obj) as $r
    | def pick(k; ok; fallback): ([$r[k], $d[k]] | map(select(ok)) | first) // fallback;
    [pick("notesAgents"; agents; ["builder"]) | any(.[]; . == $want),
     (pick("nudgeAfterToolCalls"; int(1; 999999); $dn) | floor),
     (pick("compactAtTokens"; int(1; 999999999); $dc) | floor),
     (pick("warnAtPercent"; levels; $dw | split(" ") | map(tonumber)) | map(floor) | unique | map(tostring) | join(" "))]
    | @tsv') || return 0
  IFS=$'\t' read -r cfg_opted cfg_calls cfg_compact cfg_warn <<<"$out"
  [[ "$cfg_opted" == true && -n "$want" ]] || cfg_opted=false
  [[ "$cfg_calls" =~ ^[1-9][0-9]{0,5}$ ]] || cfg_calls=$NUDGE_DEFAULT
  [[ "$cfg_compact" =~ ^[1-9][0-9]{0,8}$ ]] || cfg_compact=$COMPACT_DEFAULT
  [[ "$cfg_warn" =~ ^([1-9][0-9]{0,2}( |$))*$ ]] || cfg_warn=$WARN_DEFAULT
  return 0
}

if [[ "$scope" == main ]]; then
  # The id becomes a file name, so accept only a plain identifier
  [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
  key=$session_id
else
  [[ -n "$agent_type" ]] || exit 0
  load_config "$agent_type"
  [[ "$cfg_opted" == true ]] || exit 0
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
  for f in "$dir/$key.claim-${1:-}"*; do
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
  fi || {
    rm -f -- "$tmp"
    return 1
  }
  mv -f -- "$tmp" "$state" || {
    rm -f -- "$tmp"
    return 1
  }
  return 0
}

# Keeps one numbered claim per key; claims for the same or a higher count may be racing
sweep_older_claims() {
  local n=$1 f c
  for f in "$dir/$key".claim-*; do
    c=${f##*.claim-}
    [[ "$c" =~ ^[0-9]{1,9}$ ]] || continue
    ((10#$c < 10#$n)) || continue
    [[ -f "$f" && ! -L "$f" ]] && rm -f -- "$f"
  done
  return 0
}

# Parallel calls race: one claims each count by exclusive create (mkdir is not atomic on virtiofs)
claim() {
  local n=$1
  [[ ! -e "$dir/$key.claim-$n" && ! -L "$dir/$key.claim-$n" ]] || return 1
  (
    set -C
    : >"$dir/$key.claim-$n"
  ) 2>/dev/null || return 1
  [[ "$n" =~ ^[0-9]{1,9}$ ]] && sweep_older_claims "$n"
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

# A third argument leaves the notes text out
emit() {
  local ev=$1 ctx="$2"$'\n\n'"$RULE" body="" marker size room
  if [[ -z "${3:-}" ]] && usable_notes "$notes"; then
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

# Input tokens of the latest assistant reply since the last compaction; empty when unknown
context_tokens() {
  local file=$1
  [[ -n "$file" && -r "$file" ]] || return 0
  tail -n 200 "$file" | awk '
    index($0, "\"subtype\":\"compact_boundary\"") { buf = ""; next }
    index($0, "\"usage\"") { buf = buf $0 "\n" }
    END { printf "%s", buf }' | jq -nrR --arg scope "$scope" '
    def count: . == null or (type == "number" and . >= 0);
    [inputs | try fromjson catch null
      | select(type == "object" and .type == "assistant" and ($scope == "sub" or .isSidechain != true)
          and (.message | type) == "object" and .message.model != "<synthetic>")
      | .message.usage
      | select(type == "object" and (.input_tokens | type) == "number"
          and all(.input_tokens, .cache_creation_input_tokens, .cache_read_input_tokens; count))
      | .input_tokens + (.cache_creation_input_tokens // 0) + (.cache_read_input_tokens // 0) | floor]
    | last // empty' || true
  return 0
}

# Warns once per level per compaction cycle; a jump past several levels warns once, for the highest
context_warning() {
  local tokens level hit="" l
  [[ -n "$cfg_warn" ]] || return 1
  tokens=$(context_tokens "$(transcript_file)")
  [[ "$tokens" =~ ^[0-9]{1,12}$ ]] || return 1
  for level in $cfg_warn; do
    ((tokens * 100 >= level * cfg_compact)) && hit=$level
  done
  [[ -n "$hit" ]] || return 1
  [[ "$scope" == sub ]] || load_main_paths || return 1
  claim "warn-$hit" || return 1
  for l in $cfg_warn; do
    ((l < hit)) && claim "warn-$l"
  done
  emit PreToolUse "Your context is at $tokens tokens, $((tokens * 100 / cfg_compact))% of the $cfg_compact where it compacts. Bring your progress notes in $notes up to date now, before it compacts, so the work since your last update is not lost." nonotes
  return 0
}

notes_nudge() {
  local calls
  [[ "$scope" == sub ]] || return 0
  if usable_notes "$notes"; then
    claim nudge || true
    return 0
  fi
  [[ ! -e "$dir/$key.claim-nudge" ]] || return 0
  calls=$(count_tool_calls "$(transcript_file)")
  ((calls >= cfg_calls)) || return 0
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
    drop_claims warn-
    save_state "$count" || exit 0
    emit PreToolUse "$(compact_message)"
    exit 0
  fi
  [[ "$scope" == sub ]] || load_config ""
  context_warning && exit 0
  notes_nudge
  ;;
*) ;;
esac
exit 0
