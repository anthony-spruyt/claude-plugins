#!/usr/bin/env bats
#
# push-reviewed.sh pushes exactly the commits a reviewer approved, or stops without pushing.

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
SCRIPT="${REPO_ROOT}/agent-kit/bin/push-reviewed.sh"

setup() {
  TMP="$(mktemp -d)"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
  git init -q --bare -b main "${TMP}/origin.git"
  git clone -q "${TMP}/origin.git" "${TMP}/work" 2>/dev/null
  git clone -q "${TMP}/origin.git" "${TMP}/other" 2>/dev/null
  commit "${TMP}/work" shared.txt "one" "base"
  git -C "${TMP}/work" push -q origin HEAD:main
  git -C "${TMP}/other" pull -q origin main
  BASE="$(git -C "${TMP}/work" rev-parse HEAD)"
  git -C "${TMP}/work" checkout -q -b feature
  cd "${TMP}/work" || return 1
}

teardown() {
  cd /
  rm -rf "${TMP}"
}

commit() {
  printf '%s\n' "$3" >"$1/$2"
  git -C "$1" add "$2"
  git -C "$1" commit -q -m "$4"
}

origin_head() {
  git -C "${TMP}/origin.git" rev-parse main
}

push_reviewed() {
  run bash "${SCRIPT}" "$@"
}

@test "pushes the reviewed commits to the named remote branch and prints the pushed range" {
  commit "${TMP}/work" a.txt a "reviewed 1"
  commit "${TMP}/work" b.txt b "reviewed 2"
  reviewed="$(git rev-parse HEAD)"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -eq 0 ]
  [ "$(origin_head)" = "${reviewed}" ]
  [[ "${output}" == *"${BASE}..${reviewed}"* ]]
}

@test "stops on a dirty working tree and pushes nothing" {
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  echo dirty >"${TMP}/work/a.txt"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"not clean"* ]]
  [ "$(origin_head)" = "${BASE}" ]
}

@test "stops when untracked files are present" {
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  echo stray >"${TMP}/work/stray.txt"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [ "$(origin_head)" = "${BASE}" ]
}

@test "stops when HEAD is not the reviewed sha" {
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  commit "${TMP}/work" b.txt b "unreviewed extra"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"HEAD"* ]]
  [ "$(origin_head)" = "${BASE}" ]
}

@test "stops when the base is not on the remote branch" {
  commit "${TMP}/work" a.txt a "unreviewed local commit"
  local_base="$(git rev-parse HEAD)"
  commit "${TMP}/work" b.txt b "reviewed"
  reviewed="$(git rev-parse HEAD)"
  push_reviewed "${local_base}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"base"* ]]
  [ "$(origin_head)" = "${BASE}" ]
}

@test "stops when there are no commits between base and sha" {
  push_reviewed "${BASE}" "${BASE}" main
  [ "${status}" -ne 0 ]
  [ "$(origin_head)" = "${BASE}" ]
}

@test "stops when the base is not an ancestor of the sha" {
  commit "${TMP}/other" o.txt o "elsewhere"
  git -C "${TMP}/other" push -q origin HEAD:main
  other_tip="$(git -C "${TMP}/other" rev-parse HEAD)"
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  push_reviewed "${other_tip}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [ "$(origin_head)" = "${other_tip}" ]
}

@test "rebases onto a remote branch that moved and prints the range from the pre-push tip" {
  commit "${TMP}/other" o.txt o "someone else"
  git -C "${TMP}/other" push -q origin HEAD:main
  pre="$(git -C "${TMP}/other" rev-parse HEAD)"
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -eq 0 ]
  pushed="$(origin_head)"
  [ "${pushed}" != "${reviewed}" ]
  [ "$(git -C "${TMP}/origin.git" rev-parse "${pushed}^")" = "${pre}" ]
  [[ "${output}" == *"${pre}..${pushed}"* ]]
}

@test "aborts a conflicting rebase, leaves the clone on the reviewed sha and pushes nothing" {
  commit "${TMP}/other" shared.txt "theirs" "conflicting upstream"
  git -C "${TMP}/other" push -q origin HEAD:main
  upstream="$(git -C "${TMP}/other" rev-parse HEAD)"
  commit "${TMP}/work" shared.txt "mine" "reviewed"
  reviewed="$(git rev-parse HEAD)"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"rebase"* ]]
  [ ! -d "${TMP}/work/.git/rebase-merge" ]
  [ "$(git rev-parse HEAD)" = "${reviewed}" ]
  [ "$(origin_head)" = "${upstream}" ]
}

@test "fetches the named branch in a single-branch clone that does not track it" {
  git -C "${TMP}/work" push -q origin "${BASE}:refs/heads/side"
  git clone -q --single-branch -b side "${TMP}/origin.git" "${TMP}/single" 2>/dev/null
  cd "${TMP}/single"
  git checkout -q -b feature
  commit "${TMP}/single" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -eq 0 ]
  [ "$(origin_head)" = "${reviewed}" ]
}

@test "still reports a rebase that fails before it starts" {
  commit "${TMP}/other" o.txt o "someone else"
  git -C "${TMP}/other" push -q origin HEAD:main
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  printf '#!/bin/sh\nexit 1\n' >"${TMP}/work/.git/hooks/pre-rebase"
  chmod +x "${TMP}/work/.git/hooks/pre-rebase"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"nothing pushed"* ]]
  [ "$(origin_head)" = "$(git -C "${TMP}/other" rev-parse HEAD)" ]
}

@test "never force-pushes when the remote moves between the rebase and the push" {
  commit "${TMP}/work" a.txt a "reviewed"
  reviewed="$(git rev-parse HEAD)"
  commit "${TMP}/other" o.txt o "raced"
  printf '#!/bin/sh\ngit -C "%s" push -q origin HEAD:main\n' "${TMP}/other" >"${TMP}/work/.git/hooks/pre-push"
  chmod +x "${TMP}/work/.git/hooks/pre-push"
  push_reviewed "${BASE}" "${reviewed}" main
  [ "${status}" -ne 0 ]
  [ "$(origin_head)" = "$(git -C "${TMP}/other" rev-parse HEAD)" ]
}

@test "needs three arguments" {
  push_reviewed "${BASE}" main
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"usage"* ]]
}
