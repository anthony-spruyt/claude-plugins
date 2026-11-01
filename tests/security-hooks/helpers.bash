#!/usr/bin/env bash
# The first grep on PATH that is not the shim, so the tests also run in a shell where the shim is already first.

real_grep_path() {
  local dir dirs second
  IFS=: read -ra dirs <<<"${PATH}"
  for dir in "${dirs[@]}"; do
    [[ -f "${dir}/grep" && -x "${dir}/grep" ]] || continue
    second=''
    { IFS= read -r _ && IFS= read -r second; } 2>/dev/null <"${dir}/grep" || true
    case "${second}" in "# security-hooks grep shim"*) continue ;; *) ;; esac
    printf '%s' "${dir}/grep"
    return 0
  done
  return 1
}

# The kept names look like secret files but are not on the list
KEPT_FILES=(kept.txt sub/notes.txt environment.ts .gitignore .github/ci.yml clusterconfig.md tfstate.md secretary.yaml)
SKIPPED_FILES=(.env sub/.env .env.local app.tfstate sub/terraform.tfstate.backup clusterconfig/node.yaml
  sub/clusterconfig/deep/worker.yaml .git/config sub/.git/HEAD)

make_secret_tree() {
  local root="$1" f
  for f in "${KEPT_FILES[@]}" "${SKIPPED_FILES[@]}"; do
    mkdir -p "$(dirname -- "${root}/${f}")"
    printf 'needle\n' >"${root}/${f}"
  done
}

kept_listing() {
  printf '%s\n' "${KEPT_FILES[@]/#/$1}" | LC_ALL=C sort
}

# type -P finds the rg binary; Claude's rg is a shell function. Under CI a missing rg fails the test instead of skipping it.
require_rg() {
  RG="$(type -P rg || true)"
  if [[ -n "${RG}" ]]; then
    return 0
  fi
  if [[ -n "${CI:-}" ]]; then
    echo "rg is not installed" >&2
    return 1
  fi
  skip "rg is not installed"
}
