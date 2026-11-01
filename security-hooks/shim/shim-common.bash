# shellcheck shell=bash
# Sourced by the grep and rg shims; they set SHIM_HOME to the folder they live in first.

is_shim() {
  local file=$1 name=$2 second
  { IFS= read -r _ && IFS= read -r second; } 2>/dev/null <"$file"
  [[ $second == "# security-hooks $name shim"* ]]
}

# Sets GLOBS to the entries of secret-globs, failing when it cannot be read or has none; a directory entry ends in "/".
read_globs() {
  local glob
  GLOBS=()
  GLOBS_FILE=$SHIM_HOME/secret-globs
  [[ -r $GLOBS_FILE ]] || return 1
  while IFS= read -r glob || [[ -n $glob ]]; do
    [[ -z $glob ]] || GLOBS+=("$glob")
  done <"$GLOBS_FILE"
  ((${#GLOBS[@]} > 0))
}

find_real() {
  local name=$1 dir candidate dirs
  IFS=: read -ra dirs <<<"$PATH"
  for dir in "${dirs[@]}"; do
    [[ -n $dir ]] || continue
    candidate=$dir/$name
    [[ -f $candidate && -x $candidate ]] || continue
    ! is_shim "$candidate" "$name" || continue
    printf '%s' "$candidate"
    return 0
  done
  return 1
}
