#!/usr/bin/env bash
# The first grep on PATH that is not the shim, so the tests also run in a shell where the shim is already first.

real_grep_path() {
  local dir dirs second
  IFS=: read -ra dirs <<<"${PATH}"
  for dir in "${dirs[@]}"; do
    [ -f "${dir}/grep" ] && [ -x "${dir}/grep" ] || continue
    second=''
    { IFS= read -r _ && IFS= read -r second; } 2>/dev/null <"${dir}/grep" || true
    case "${second}" in "# security-hooks grep shim"*) continue ;; esac
    printf '%s' "${dir}/grep"
    return 0
  done
  return 1
}
