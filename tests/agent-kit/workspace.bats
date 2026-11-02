#!/usr/bin/env bats
#
# workspace.sh gives an agent its own full clone on a fresh branch, or stops without leaving one.
# When the repo uses pre-commit, the clone gets its git hook too, and a failed install never fails the clone.

bats_require_minimum_version 1.5.0

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
SCRIPT="${REPO_ROOT}/agent-kit/bin/workspace.sh"

setup() {
  TMP="$(mktemp -d)"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
  export AGENT_WORKSPACE_REMOTE_BASE="${TMP}/remotes/"
  export AGENT_WORKSPACE_ROOT="${TMP}/work"
  mkdir -p "${TMP}/remotes/acme"
  git init -q --bare -b trunk "${TMP}/remotes/acme/widget.git"
  git clone -q "${TMP}/remotes/acme/widget.git" "${TMP}/seed" 2>/dev/null
  printf 'hello\n' >"${TMP}/seed/file.txt"
  git -C "${TMP}/seed" add file.txt
  git -C "${TMP}/seed" commit -q -m seed
  git -C "${TMP}/seed" push -q origin HEAD:trunk
}

teardown() {
  rm -rf "${TMP}"
}

workspace() {
  run bash "${SCRIPT}" "$@"
}

seed_hooked_remote() {
  git init -q --bare -b trunk "${TMP}/remotes/acme/hooked.git"
  git clone -q "${TMP}/remotes/acme/hooked.git" "${TMP}/seed-hooked" 2>/dev/null
  printf 'repos: []\n' >"${TMP}/seed-hooked/.pre-commit-config.yaml"
  git -C "${TMP}/seed-hooked" add .pre-commit-config.yaml
  git -C "${TMP}/seed-hooked" commit -q -m seed
  git -C "${TMP}/seed-hooked" push -q origin HEAD:trunk
}

stub_pre_commit() {
  STUB_CALLS="${TMP}/pre-commit-calls"
  export STUB_CALLS
  mkdir -p "${TMP}/stub-bin"
  cat >"${TMP}/stub-bin/pre-commit" <<'EOF'
#!/usr/bin/env bash
printf '%s|%s\n' "$PWD" "$*" >>"${STUB_CALLS}"
echo "stub-pre-commit-stdout"
echo "stub-pre-commit-stderr" >&2
exit "${STUB_EXIT:-0}"
EOF
  chmod +x "${TMP}/stub-bin/pre-commit"
  PATH="${TMP}/stub-bin:${PATH}"
}

# Only the tools the script needs, so a pre-commit installed on this machine is not found.
without_pre_commit() {
  mkdir -p "${TMP}/min-bin"
  for tool in bash git mktemp mkdir rm; do
    ln -s "$(command -v "${tool}")" "${TMP}/min-bin/${tool}"
  done
  run --separate-stderr env PATH="${TMP}/min-bin" "${BASH}" "${SCRIPT}" "$@"
}

@test "prints the path of a new clone named after repo and task" {
  workspace acme/widget fix-thing
  [ "${status}" -eq 0 ]
  [[ "${output}" =~ ^${AGENT_WORKSPACE_ROOT}/widget-fix-thing-[A-Za-z0-9]{4,}$ ]]
  [ -f "${output}/file.txt" ]
  [ -d "${output}/.git" ]
}

@test "creates a branch named after the task from the default branch" {
  workspace acme/widget fix-thing
  [ "${status}" -eq 0 ]
  [ "$(git -C "${output}" branch --show-current)" = "fix-thing" ]
  [ "$(git -C "${output}" rev-parse HEAD)" = "$(git -C "${TMP}/seed" rev-parse HEAD)" ]
}

@test "two calls with the same task get different directories" {
  workspace acme/widget same
  first="${output}"
  workspace acme/widget same
  [ "${status}" -eq 0 ]
  [ "${first}" != "${output}" ]
}

@test "prints only the path on stdout" {
  run --separate-stderr bash "${SCRIPT}" acme/widget fix-thing
  [ "${status}" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
}

@test "rejects a task name that is not a plain slug" {
  for bad in "Fix" "a b" "../x" "x/y" "-x" "x;y" "x\$y" ""; do
    workspace acme/widget "${bad}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"task name"* ]]
  done
  [ ! -e "${AGENT_WORKSPACE_ROOT}" ] || [ -z "$(ls -A "${AGENT_WORKSPACE_ROOT}")" ]
}

@test "rejects a repo that is not owner/name" {
  for bad in "widget" "acme/widget/x" "../acme/widget" "acme/.." "acme/wid get" ""; do
    workspace "${bad}" fix-thing
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owner/repo"* ]]
  done
}

@test "needs both arguments" {
  workspace acme/widget
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"Usage"* ]]
}

@test "a failed clone leaves no directory behind and exits non-zero" {
  workspace acme/missing fix-thing
  [ "${status}" -ne 0 ]
  [ -z "$(ls -A "${AGENT_WORKSPACE_ROOT}")" ]
}

@test "installs the pre-commit hook in the clone when the repo has a config" {
  seed_hooked_remote
  stub_pre_commit
  workspace acme/hooked fix-thing
  [ "${status}" -eq 0 ]
  [ "$(cat "${STUB_CALLS}")" = "${output##*$'\n'}|install" ]
}

@test "does not run pre-commit when the repo has no config" {
  stub_pre_commit
  workspace acme/widget fix-thing
  [ "${status}" -eq 0 ]
  [ ! -e "${STUB_CALLS}" ]
}

@test "runs install only, so no hook environments are built" {
  seed_hooked_remote
  stub_pre_commit
  workspace acme/hooked fix-thing
  [ "${status}" -eq 0 ]
  [ "$(wc -l <"${STUB_CALLS}")" -eq 1 ]
  [[ "$(cat "${STUB_CALLS}")" == *"|install" ]]
}

@test "pre-commit output goes to stderr and stdout stays the path" {
  seed_hooked_remote
  stub_pre_commit
  run --separate-stderr bash "${SCRIPT}" acme/hooked fix-thing
  [ "${status}" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ -d "${output}/.git" ]
  [[ "${stderr}" == *"stub-pre-commit-stdout"* ]]
  [[ "${stderr}" == *"stub-pre-commit-stderr"* ]]
}

@test "a missing pre-commit gives one warning and the clone still succeeds" {
  seed_hooked_remote
  without_pre_commit acme/hooked fix-thing
  [ "${status}" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ -f "${output}/.pre-commit-config.yaml" ]
  [ "${#stderr_lines[@]}" -eq 1 ]
  [[ "${stderr}" == *"warning"*"pre-commit"* ]]
}

@test "a failed pre-commit install gives one warning and the clone still succeeds" {
  seed_hooked_remote
  stub_pre_commit
  STUB_EXIT=1
  export STUB_EXIT
  run --separate-stderr bash "${SCRIPT}" acme/hooked fix-thing
  [ "${status}" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [ "$(git -C "${output}" branch --show-current)" = "fix-thing" ]
  [ "$(grep -c "warning" <<<"${stderr}")" -eq 1 ]
}

@test "a repo without a pre-commit config gets no warning even when pre-commit is missing" {
  without_pre_commit acme/widget fix-thing
  [ "${status}" -eq 0 ]
  [ -z "${stderr}" ]
}
