#!/usr/bin/env bats
#
# ci-status.sh reduces a PR's or a commit's CI to one word and an exit code.

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
SCRIPT="${REPO_ROOT}/agent-kit/bin/ci-status.sh"
SHA="0123456789abcdef0123456789abcdef01234567"

setup() {
  BIN="$(mktemp -d)"
  FIX="${BIN}/fixtures"
  mkdir -p "${FIX}"
  : >"${BIN}/curl.log"
  : >"${BIN}/sleep.log"
  : >"${BIN}/gh.log"

  cat >"${BIN}/gh" <<'STUB'
#!/bin/bash
FIX="$(dirname "$0")/fixtures"
echo "$*" >>"$(dirname "$0")/gh.log"
# Serves FIX/<name>.<call number>.json when present, else FIX/<name>.json.
serve() {
  local n=1 f
  [ -f "${FIX}/$1.count" ] && n=$(($(cat "${FIX}/$1.count") + 1))
  echo "${n}" >"${FIX}/$1.count"
  f="${FIX}/$1.${n}.json"
  [ -f "${f}" ] || f="${FIX}/$1.json"
  if [ -f "${f}" ]; then cat "${f}"; else echo "${2:-[]}"; fi
}
case "$*" in
  "pr checks"*)
    [ -f "${FIX}/pr-checks.err" ] && cat "${FIX}/pr-checks.err" >&2
    [ -f "${FIX}/pr-checks.nojson" ] || serve pr-checks
    [ -f "${FIX}/pr-checks.rc" ] && exit "$(cat "${FIX}/pr-checks.rc")"
    exit 0 ;;
  "pr view"*) echo '{"headRefOid":"0123456789abcdef0123456789abcdef01234567"}' ;;
  "run list"*)
    [ -f "${FIX}/runs.rc" ] && { echo "run list broke" >&2; exit "$(cat "${FIX}/runs.rc")"; }
    serve runs ;;
  "api "*check-runs*) serve check-runs '{"check_runs":[]}' ;;
  "api "*/status*) serve status '{"state":"pending","total_count":0,"statuses":[]}' ;;
  "api "*code-scanning*) serve alerts ;;
  *) echo "unexpected gh call: $*" >&2; exit 99 ;;
esac
STUB

  cat >"${BIN}/curl" <<'STUB'
#!/bin/bash
FIX="$(dirname "$0")/fixtures"
echo "$*" >>"$(dirname "$0")/curl.log"
case "$*" in
  *qualitygates*) cat "${FIX}/sonar-gate.json" ;;
  *issues/search*) cat "${FIX}/sonar-issues.json" ;;
  *) exit 99 ;;
esac
STUB

  cat >"${BIN}/sleep" <<'STUB'
#!/bin/bash
echo "$*" >>"$(dirname "$0")/sleep.log"
STUB
  chmod +x "${BIN}/gh" "${BIN}/curl" "${BIN}/sleep"
  export PATH="${BIN}:${PATH}"
}

teardown() {
  rm -rf "${BIN}"
}

fixture() {
  printf '%s\n' "$2" >"${FIX}/$1"
}

pr_ok() {
  fixture sonar-gate.json '{"projectStatus":{"status":"OK"}}'
  fixture sonar-issues.json '{"total":0}'
  fixture alerts.json '[]'
}

first_line() {
  printf '%s\n' "${output}" | head -n 1
}

ci() {
  run bash "${SCRIPT}" "$@"
}

@test "a PR whose checks all pass or skip is green" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"},{"name":"lint","bucket":"skipping"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 0 ]
  [ "$(first_line)" = "green" ]
}

@test "a pending or failing Mergify Merge Protections check is ignored" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"},{"name":"Mergify Merge Protections","bucket":"pending"}]'
  fixture pr-checks.rc 8
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 0 ]
  [ "$(first_line)" = "green" ]

  fixture pr-checks.json '[{"name":"build","bucket":"pass"},{"name":"Mergify Merge Protections","bucket":"fail"}]'
  fixture pr-checks.rc 1
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 0 ]
  [ "$(first_line)" = "green" ]
}

@test "a failing check makes the PR failed and names the check" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"},{"name":"unit tests","bucket":"fail"}]'
  fixture pr-checks.rc 1
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 1 ]
  [ "$(first_line)" = "failed" ]
  [[ "${output}" == *"unit tests"* ]]
  [[ "${output}" != *"build"* ]]
}

@test "a cancelled check counts as failed" {
  fixture pr-checks.json '[{"name":"build","bucket":"cancel"}]'
  fixture pr-checks.rc 1
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 1 ]
  [ "$(first_line)" = "failed" ]
}

@test "a pending check makes the PR pending and names the check" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"},{"name":"e2e","bucket":"pending"}]'
  fixture pr-checks.rc 8
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 2 ]
  [ "$(first_line)" = "pending" ]
  [[ "${output}" == *"e2e"* ]]
}

@test "a failure outranks a pending check" {
  fixture pr-checks.json '[{"name":"e2e","bucket":"pending"},{"name":"lint","bucket":"fail"}]'
  fixture pr-checks.rc 8
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 1 ]
  [ "$(first_line)" = "failed" ]
}

@test "only Mergify checks, an empty listing and 'no checks reported' are all not-started" {
  fixture pr-checks.json '[{"name":"Mergify Merge Protections","bucket":"pending"},{"name":"Mergify Merge Queue","bucket":"skipping"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 3 ]
  [ "$(first_line)" = "not-started" ]

  fixture pr-checks.json '[]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 3 ]

  fixture pr-checks.nojson 1
  fixture pr-checks.err "no checks reported on the 'feature' branch"
  fixture pr-checks.rc 1
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 3 ]
  [ "$(first_line)" = "not-started" ]
}

@test "a gh pr checks failure that is not a check status is an error" {
  fixture pr-checks.nojson 1
  fixture pr-checks.err "GraphQL: Could not resolve to a PullRequest with the number of 7."
  fixture pr-checks.rc 1
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 4 ]
  [ "$(first_line)" = "error" ]
  [[ "${output}" == *"Could not resolve"* ]]

  rm "${FIX}/pr-checks.err"
  fixture pr-checks.err "HTTP 401: Bad credentials"
  fixture pr-checks.rc 4
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 4 ]
}

@test "a workflow run waiting for approval returns pending even with no checks listed" {
  fixture pr-checks.json '[]'
  fixture runs.json '[{"name":"CI","status":"waiting","conclusion":""}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 2 ]
  [ "$(first_line)" = "pending" ]
  [[ "${output}" == *"CI"*"needs approval"* ]]
}

@test "green PR checks then Sonar gate OK, zero issues and zero CodeQL alerts is green" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  ci --repo octo/repo --pr 7
  [ "${status}" -eq 0 ]
  [ "$(first_line)" = "green" ]
  [[ "$(sed -n 1p "${BIN}/curl.log")" == *"qualitygates/project_status?projectKey=octo_repo&pullRequest=7"* ]]
  [[ "$(sed -n 2p "${BIN}/curl.log")" == *"issues/search?componentKeys=octo_repo&pullRequest=7&resolved=false"* ]]
  grep -q 'code-scanning/alerts?ref=refs/pull/7/merge&state=open' "${BIN}/gh.log"
}

@test "a Sonar gate that is not OK fails the PR before the issue count is read" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  fixture sonar-gate.json '{"projectStatus":{"status":"ERROR"}}'
  ci --repo o/r --pr 7
  [ "${status}" -eq 1 ]
  [ "$(first_line)" = "failed" ]
  [[ "${output}" == *"sonar"*"ERROR"* ]]
  [ "$(wc -l <"${BIN}/curl.log")" -eq 1 ]
}

@test "a Sonar errors response for a bad key is an error that says so, not an issue count of zero" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  fixture sonar-gate.json '{"errors":[{"msg":"Project not found"}]}'
  ci --repo o/r --pr 7
  [ "${status}" -eq 4 ]
  [ "$(first_line)" = "error" ]
  [[ "${output}" == *"o_r"* ]]
  [[ "${output}" == *"--sonar-key"* ]]
}

@test "open Sonar issues fail the PR" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  fixture sonar-issues.json '{"total":3}'
  ci --repo o/r --pr 7
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"sonar"*"3"* ]]
  [[ "${output}" == *"issues/search?componentKeys=o_r&pullRequest=7&resolved=false"* ]]
}

@test "open CodeQL alerts on the PR merge ref fail the PR" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  fixture alerts.json '[{"number":1},{"number":2}]'
  ci --repo o/r --pr 7
  [ "${status}" -eq 1 ]
  [ "$(first_line)" = "failed" ]
  [[ "${output}" == *"codeql"*"2"* ]]
}

@test "every curl call has a 20 second time limit" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  ci --repo o/r --pr 7
  [ "$(wc -l <"${BIN}/curl.log")" -eq 2 ]
  [ -z "$(grep -v -e '--max-time 20' "${BIN}/curl.log" || true)" ]
}

@test "--no-sonar keeps the CodeQL gate and --no-codeql keeps the Sonar gate" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  fixture alerts.json '[{"number":1}]'
  ci --repo o/r --pr 7 --no-sonar
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"codeql"* ]]
  [ ! -s "${BIN}/curl.log" ]

  : >"${BIN}/gh.log"
  fixture sonar-gate.json '{"projectStatus":{"status":"ERROR"}}'
  ci --repo o/r --pr 7 --no-codeql
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"sonar"* ]]
  [[ "${output}" != *"codeql"* ]]
  [ -z "$(grep code-scanning "${BIN}/gh.log" || true)" ]
}

@test "--sonar-key replaces the default project key" {
  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  pr_ok
  ci --repo o/r --pr 7 --sonar-key custom_key
  [ "${status}" -eq 0 ]
  [[ "$(sed -n 1p "${BIN}/curl.log")" == *"projectKey=custom_key"* ]]
}

@test "Sonar and CodeQL are not consulted while checks are pending or with both skipped" {
  fixture pr-checks.json '[{"name":"e2e","bucket":"pending"}]'
  fixture pr-checks.rc 8
  ci --repo o/r --pr 7
  [ "${status}" -eq 2 ]
  [ ! -s "${BIN}/curl.log" ]
  [ -z "$(grep code-scanning "${BIN}/gh.log" || true)" ]

  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  fixture pr-checks.rc 0
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 0 ]
  [ ! -s "${BIN}/curl.log" ]
}

sha_green() {
  fixture check-runs.json '{"check_runs":[{"name":"build","status":"completed","conclusion":"success"},{"name":"docs","status":"completed","conclusion":"skipped"},{"name":"adv","status":"completed","conclusion":"neutral"}]}'
  fixture runs.json '[{"name":"CI","status":"completed","conclusion":"success"}]'
}

@test "a main commit with every check-run and workflow run complete is green" {
  sha_green
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 0 ]
  [ "$(first_line)" = "green" ]
  [ ! -s "${BIN}/curl.log" ]
  grep -q "repos/o/r/commits/${SHA}/check-runs?per_page=100" "${BIN}/gh.log"
}

@test "a commit status of pending with no statuses reported is not pending" {
  sha_green
  fixture status.json '{"state":"pending","total_count":0,"statuses":[]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 0 ]
}

@test "a failed or errored commit status (Terraform Cloud) fails the commit" {
  sha_green
  fixture status.json '{"state":"failure","total_count":1,"statuses":[{"context":"Terraform Cloud/ws","state":"failure"}]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"Terraform Cloud/ws"* ]]

  fixture status.json '{"state":"error","total_count":1,"statuses":[{"context":"Terraform Cloud/ws","state":"error"}]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 1 ]
}

@test "a pending commit status with statuses reported is pending" {
  sha_green
  fixture status.json '{"state":"pending","total_count":1,"statuses":[{"context":"Terraform Cloud/ws","state":"pending"}]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"Terraform Cloud/ws"* ]]
}

@test "a failed check-run fails the commit and an unfinished one is pending" {
  sha_green
  fixture check-runs.json '{"check_runs":[{"name":"build","status":"completed","conclusion":"failure"},{"name":"e2e","status":"in_progress","conclusion":null}]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"build"* ]]

  fixture check-runs.json '{"check_runs":[{"name":"e2e","status":"in_progress","conclusion":null}]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"e2e"* ]]
}

@test "a Mergify Merge Protections check-run is ignored on a commit" {
  sha_green
  fixture check-runs.json '{"check_runs":[{"name":"build","status":"completed","conclusion":"success"},{"name":"Mergify Merge Protections","status":"in_progress","conclusion":null}]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 0 ]
}

@test "a commit with no workflow runs or no check-runs is not-started" {
  sha_green
  fixture runs.json '[]'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 3 ]
  [ "$(first_line)" = "not-started" ]

  sha_green
  fixture check-runs.json '{"check_runs":[]}'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 3 ]
}

@test "a workflow run that is not completed keeps the commit pending" {
  sha_green
  fixture runs.json '[{"name":"CI","status":"queued","conclusion":""}]'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"CI"* ]]
}

@test "a completed workflow run that failed fails the commit" {
  sha_green
  fixture runs.json '[{"name":"CI","status":"completed","conclusion":"startup_failure"}]'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"CI"* ]]
}

@test "--wait polls every 60 seconds until the PR turns green" {
  fixture pr-checks.1.json '[{"name":"e2e","bucket":"pending"}]'
  fixture pr-checks.2.json '[{"name":"e2e","bucket":"pending"}]'
  fixture pr-checks.3.json '[{"name":"e2e","bucket":"pass"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql --wait
  [ "${status}" -eq 0 ]
  [ "$(first_line)" = "green" ]
  [ "$(cat "${BIN}/sleep.log")" = "$(printf '60\n60')" ]
}

@test "--wait gives up after --timeout minutes and returns the last status" {
  fixture pr-checks.json '[{"name":"e2e","bucket":"pending"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql --wait --timeout 3
  [ "${status}" -eq 2 ]
  [ "$(first_line)" = "pending" ]
  [ "$(wc -l <"${BIN}/sleep.log")" -eq 3 ]
}

@test "--wait defaults to an 8 minute timeout" {
  fixture pr-checks.json '[{"name":"e2e","bucket":"pending"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql --wait
  [ "${status}" -eq 2 ]
  [ "$(wc -l <"${BIN}/sleep.log")" -eq 8 ]
}

@test "--wait keeps polling while CI has not started and then reports not-started" {
  fixture pr-checks.json '[]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql --wait --timeout 2
  [ "${status}" -eq 3 ]
  [ "$(first_line)" = "not-started" ]
  [ "$(wc -l <"${BIN}/sleep.log")" -eq 2 ]
}

@test "--wait returns a failure at once" {
  fixture pr-checks.json '[{"name":"lint","bucket":"fail"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql --wait
  [ "${status}" -eq 1 ]
  [ ! -s "${BIN}/sleep.log" ]
}

@test "--wait returns at once when a run is waiting for approval" {
  fixture pr-checks.json '[{"name":"lint","bucket":"pending"}]'
  fixture runs.json '[{"name":"CI","status":"waiting","conclusion":""}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql --wait
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"needs approval"* ]]
  [ ! -s "${BIN}/sleep.log" ]
}

@test "without --wait a pending PR returns at once" {
  fixture pr-checks.json '[{"name":"e2e","bucket":"pending"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 2 ]
  [ ! -s "${BIN}/sleep.log" ]
}

@test "a gh command that fails mid-way is an error, never a CI status" {
  sha_green
  fixture runs.rc 1
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 4 ]
  [[ "${output}" == *error* ]]

  fixture pr-checks.json '[{"name":"build","bucket":"pass"}]'
  ci --repo o/r --pr 7 --no-sonar --no-codeql
  [ "${status}" -eq 4 ]
  [[ "${output}" == *error* ]]
}

@test "non-JSON output from gh with exit 0 is an error, never not-started" {
  sha_green
  fixture runs.json 'oops'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 4 ]
  [ "$(first_line)" = "error" ]

  sha_green
  fixture status.json 'oops'
  ci --repo o/r --sha "${SHA}"
  [ "${status}" -eq 4 ]
  [ "$(first_line)" = "error" ]
}

@test "--help documents the statuses and exit codes" {
  ci --help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"0 green, 1 failed, 2 pending, 3 not-started, 4 error"* ]]
  [[ "${output}" == *"--no-sonar"* && "${output}" == *"--no-codeql"* ]]
}

@test "bad arguments are an error" {
  ci --pr 7
  [ "${status}" -eq 4 ]
  ci --repo o/r
  [ "${status}" -eq 4 ]
  ci --repo o/r --pr 7 --sha "${SHA}"
  [ "${status}" -eq 4 ]
  ci --repo o/r --sha abc123
  [ "${status}" -eq 4 ]
  ci --repo o/r --pr 7 --wait --timeout soon
  [ "${status}" -eq 4 ]
  ci --repo o/r --pr 7 --bogus
  [ "${status}" -eq 4 ]
}
