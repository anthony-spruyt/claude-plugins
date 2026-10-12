#!/usr/bin/env bats
#
# workspace.sh gives an agent its own full clone on a fresh branch, or stops without leaving one.

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
  for bad in "Fix" "a b" "../x" "x/y" "-x" "x;y" 'x$y' ""; do
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
