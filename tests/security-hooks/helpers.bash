#!/usr/bin/env bash
# The first command with this name on PATH that is not the shim, so the tests also run in a shell where the shims are already first.

real_path() {
  local name="$1" dir dirs second
  IFS=: read -ra dirs <<<"${PATH}"
  for dir in "${dirs[@]}"; do
    [[ -f "${dir}/${name}" && -x "${dir}/${name}" ]] || continue
    second=''
    { IFS= read -r _ && IFS= read -r second; } 2>/dev/null <"${dir}/${name}" || true
    case "${second}" in "# security-hooks ${name} shim"*) continue ;; *) ;; esac
    printf '%s' "${dir}/${name}"
    return 0
  done
  return 1
}

real_grep_path() {
  real_path grep
}

# The kept names look like secret files but are not on the list
KEPT_FILES=(kept.txt sub/notes.txt environment.ts .gitignore .github/ci.yml clusterconfig.md tfstate.md secretary.yaml hosts.txt
  envrc.md environ.md)
SKIPPED_FILES=(.env sub/.env .env.local .envrc app.tfstate sub/terraform.tfstate.backup clusterconfig/node.yaml
  sub/clusterconfig/deep/worker.yaml .git/config .git/refs/heads/main sub/.git/HEAD .kube/config .aws/credentials
  .config/gh/hosts.yml .terraform.d/credentials.tfrc.json sub/secrets.yaml.bak deploy_id_rsa proc/1/environ)

make_secret_tree() {
  local root="$1" f
  for f in "${KEPT_FILES[@]}" "${SKIPPED_FILES[@]}"; do
    mkdir -p "$(dirname -- "${root}/${f}")"
    printf 'needle\n' >"${root}/${f}"
  done
}

kept_listing() {
  local prefix="$1"
  printf '%s\n' "${KEPT_FILES[@]/#/${prefix}}" | LC_ALL=C sort
}

# A PATH search finds the rg binary; Claude's rg is a shell function. Under CI a missing rg fails the test instead of skipping it.
require_rg() {
  RG="$(real_path rg || true)"
  if [[ -n "${RG}" ]]; then
    return 0
  fi
  if [[ -n "${CI:-}" ]]; then
    echo "rg is not installed" >&2
    return 1
  fi
  skip "rg is not installed"
}
