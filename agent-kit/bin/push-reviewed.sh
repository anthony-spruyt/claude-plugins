#!/usr/bin/env bash
# Pushes the commits a reviewer approved (<base>..<sha>) to origin/<branch>, creating the branch when origin lacks it, or stops without pushing.
# It also stops when any commit it would push is unsigned or has a bad signature.
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

# Origin's branch tips come from the server's listing, never from local ref names.
remote_heads=$(git ls-remote --heads origin) || fail "cannot list origin heads"
pre_push=""
while read -r tip ref; do
  if [[ "${ref}" == "refs/heads/${branch}" ]]; then pre_push="${tip}"; fi
done <<<"${remote_heads}"

if [[ -n "${pre_push}" ]]; then
  git fetch --quiet origin "+refs/heads/${branch}:refs/remotes/origin/${branch}" || fail "cannot fetch origin ${branch}"
  git merge-base --is-ancestor "${base}" "${pre_push}" ||
    fail "base ${base} is not on origin/${branch}: unreviewed commits sit below the range"
else
  git fetch --quiet origin "+refs/heads/*:refs/remotes/origin/*" || fail "cannot fetch origin"
  published=""
  while read -r tip _; do
    if [[ -n "${tip}" ]] && git merge-base --is-ancestor "${base}" "${tip}" 2>/dev/null; then published=1; fi
  done <<<"${remote_heads}"
  [[ -n "${published}" ]] || fail "base ${base} is not on any origin branch: unreviewed commits sit below the range"
  pre_push="${base}"
fi

git merge-base --is-ancestor "${base}" "${sha}" || fail "base ${base} is not an ancestor of ${sha}"
[[ -n "$(git rev-list "${base}..${sha}")" ]] || fail "no commits between ${base} and ${sha}"

# Rebasing flattens merge commits and replays their conflicts, so only rebase when the remote is not an ancestor of HEAD.
if ! git merge-base --is-ancestor "${pre_push}" HEAD && ! git rebase --quiet "${pre_push}" >/dev/null 2>&1; then
  git rebase --abort 2>/dev/null || true
  fail "rebase onto origin/${branch} conflicts: nothing pushed"
fi

# Checked after the rebase, which re-creates commits. Reads the gpgsig header, not %G?: without an allowed-signers file %G? reports every signed commit as N.
unsigned=()
while read -r commit; do
  raw=$(git cat-file commit "${commit}")
  [[ "${raw%%$'\n\n'*}" == *$'\ngpgsig'* && "$(git log -1 --format=%G? "${commit}" 2>/dev/null)" != "B" ]] ||
    unsigned+=("$(git rev-parse --short "${commit}")")
done < <(git rev-list "${pre_push}..HEAD")
[[ ${#unsigned[@]} -eq 0 ]] || fail "unsigned or badly signed commits in ${pre_push}..HEAD: ${unsigned[*]}: nothing pushed"

git push --quiet origin "HEAD:refs/heads/${branch}" || fail "push to origin ${branch} was rejected: nothing forced"

printf '%s..%s\n' "${pre_push}" "$(git rev-parse HEAD)"
