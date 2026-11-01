#!/usr/bin/env bash
# SessionStart hook: puts the grep and rg shims, their helper, secret-globs and the rg config built from the globs in the plugin data dir
# and points the Bash tool's shell at them.
# Any failure leaves nothing installed and the session starts as usual. Stdout becomes session context, so it stays empty.
set -u

[[ ${SECURITY_HOOKS_GREP_SHIM:-} != 0 ]] || exit 0
env_file=${CLAUDE_ENV_FILE:-}
data_dir=${CLAUDE_PLUGIN_DATA:-}
[[ -n $env_file && -n $data_dir ]] || exit 0

source_dir=${BASH_SOURCE[0]%/*}/../shim
[[ -f $source_dir/grep && -f $source_dir/rg && -f $source_dir/shim-common.bash && -f $source_dir/secret-globs ]] || exit 0
shim_dir=$data_dir/shim
rg_config=$shim_dir/ripgreprc

SHIM_HOME=$source_dir
# shellcheck source-path=SCRIPTDIR source=../shim/shim-common.bash
source "$source_dir/shim-common.bash"
install_rg=0
! find_real rg >/dev/null || install_rg=1

# A rename keeps sessions that are running grep right now on a complete file
install_file() {
  local from=$1 to=$2 mode=$3 tmp
  if cmp -s "$from" "$to" && [[ -x $to || $mode != 755 ]]; then
    return 0
  fi
  tmp=$(mktemp "$shim_dir/.install.XXXXXX") || return 1
  if cp "$from" "$tmp" && chmod "$mode" "$tmp" && mv -f "$tmp" "$to"; then
    return 0
  fi
  rm -f "$tmp"
  return 1
}

write_rg_config() {
  local tmp glob status=0
  tmp=$(mktemp) || return 1
  # A folder gets two globs: the first prunes the walk, the second also covers a folder passed by name
  while IFS= read -r glob || [[ -n $glob ]]; do
    [[ -z $glob ]] || printf -- '--glob=!%s\n' "$glob"
    [[ $glob != */ ]] || printf -- '--glob=!**/%s**\n' "$glob"
  done <"$source_dir/secret-globs" >"$tmp"
  install_file "$tmp" "$rg_config" 644 || status=1
  rm -f "$tmp"
  return "$status"
}

grep_works() {
  local dir=$1 out
  out=$("$shim_dir/grep" --version | head -n 1)
  [[ $out == "grep (GNU grep)"* ]] || return 1
  out=$(cd "$dir" && "$shim_dir/grep" -rl needle . && "$shim_dir/grep" -l needle skipped.sops.txt .git/config)
  [[ $out == ./kept.txt ]]
}

# -g '*' lists every file when nothing excludes any; the path is explicit because rg reads a piped stdin when it has none
rg_works() {
  local dir=$1 out
  out=$(cd "$dir" && unset RIPGREP_CONFIG_PATH && "$shim_dir/rg" -g '*' -l needle . </dev/null)
  [[ $out == ./kept.txt ]]
}

works() {
  local dir name status=1
  dir=$(mktemp -d) || return 1
  mkdir "$dir/.git"
  for name in kept.txt skipped.sops.txt .git/config; do
    printf 'needle\n' >"$dir/$name"
  done
  if grep_works "$dir" && { ((install_rg == 0)) || rg_works "$dir"; }; then
    status=0
  fi
  rm -rf "$dir"
  return "$status"
}

# Single quotes, so nothing in the path is expanded when the line is sourced
quote() {
  local escaped=${1//\'/\'\\\'\'}
  printf "'%s'" "$escaped"
}

append_line() {
  local line=$1 existing
  if [[ -f $env_file ]]; then
    while IFS= read -r existing || [[ -n $existing ]]; do
      [[ $existing != "$line" ]] || return 0
    done <"$env_file"
    # A file without a trailing newline would glue the line onto its last one
    if [[ -s $env_file && -n $(tail -c1 "$env_file") ]]; then
      printf '\n' >>"$env_file"
    fi
  fi
  printf '%s\n' "$line" >>"$env_file"
}

mkdir -p "$shim_dir" || exit 0
# The shims go last: a running session's shim stops when it cannot read the list or the helper, and a failed step keeps the old shim
install_file "$source_dir/secret-globs" "$shim_dir/secret-globs" 644 || exit 0
install_file "$source_dir/shim-common.bash" "$shim_dir/shim-common.bash" 644 || exit 0
write_rg_config || exit 0
install_file "$source_dir/grep" "$shim_dir/grep" 755 || exit 0
if ((install_rg)); then
  install_file "$source_dir/rg" "$shim_dir/rg" 755 || exit 0
fi
works || exit 0

q_dir=$(quote "$shim_dir")
q_config=$(quote "$rg_config")
# shellcheck disable=SC2016
append_line 'case ":$PATH:" in *:'"$q_dir"':*) ;; *) PATH='"$q_dir"':"$PATH" ;; esac'
# shellcheck disable=SC2016
append_line 'if [ -z "${RIPGREP_CONFIG_PATH+x}" ] && [ "${SECURITY_HOOKS_GREP_SHIM:-}" != 0 ] && [ -f '"$q_config"' ]; then export RIPGREP_CONFIG_PATH='"$q_config"'; fi'
exit 0
