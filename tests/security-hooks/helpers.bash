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

# type -P finds the rg binary; Claude's rg is a shell function. Under CI a missing rg fails the test instead of skipping it.
require_rg() {
  RG="$(type -P rg || true)"
  if [ -n "${RG}" ]; then
    return 0
  fi
  if [ -n "${CI:-}" ]; then
    echo "rg is not installed" >&2
    return 1
  fi
  skip "rg is not installed"
}
