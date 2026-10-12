#!/usr/bin/env bash
# Pushes the commits a reviewer approved (<base>..<sha>) to origin/<branch>, or stops without pushing.
# Run it from the clone that holds them. Prints the pushed range, <pre-push tip>..<pushed sha>.
set -euo pipefail

fail() {
  printf 'push-reviewed: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 3 ]] || fail "usage: push-reviewed.sh <base> <sha> <branch>"
base="$1" sha="$2" branch="$3"

base=$(git rev-parse --verify --quiet "${base}^{commit}") || fail "base ${1} is not a commit"
sha=$(git rev-parse --verify --quiet "${sha}^{commit}") || fail "sha ${2} is not a commit"

[[ -z "$(git status --porcelain)" ]] || fail "working tree is not clean"
[[ "$(git rev-parse HEAD)" == "${sha}" ]] || fail "HEAD is not the reviewed sha ${sha}"

git fetch --quiet origin "+refs/heads/${branch}:refs/remotes/origin/${branch}" || fail "cannot fetch origin ${branch}"
pre_push=$(git rev-parse --verify --quiet "origin/${branch}") || fail "origin/${branch} not found"
git merge-base --is-ancestor "${base}" "${pre_push}" ||
  fail "base ${base} is not on origin/${branch}: unreviewed commits sit below the range"

git merge-base --is-ancestor "${base}" "${sha}" || fail "base ${base} is not an ancestor of ${sha}"
[[ -n "$(git rev-list "${base}..${sha}")" ]] || fail "no commits between ${base} and ${sha}"

if ! git rebase --quiet "${pre_push}" >/dev/null 2>&1; then
  git rebase --abort 2>/dev/null || true
  fail "rebase onto origin/${branch} conflicts: nothing pushed"
fi

git push --quiet origin "HEAD:${branch}" || fail "push to origin ${branch} was rejected: nothing forced"

printf '%s..%s\n' "${pre_push}" "$(git rev-parse HEAD)"
