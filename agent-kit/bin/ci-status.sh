#!/usr/bin/env bash
# Reduces the CI of a PR or a commit to one word: green, pending, failed or not-started.
set -eEuo pipefail
trap 'printf "error\nunexpected failure near line %s\n" "${LINENO}"; exit 4' ERR

readonly IGNORED_CHECKS='["Mergify Merge Protections","Mergify Merge Queue"]'
readonly INTERVAL=60

usage() {
  cat <<'EOF'
usage: ci-status.sh --repo <owner/repo> (--pr <n> | --sha <full-sha>) [--wait [--timeout <min>]]
                    [--sonar-key <key>] [--no-sonar] [--no-codeql]

Prints green, pending, failed, not-started or error on the first line, then the checks behind it.
Exit codes: 0 green, 1 failed, 2 pending, 3 not-started, 4 error.
--wait polls every 60s for --timeout minutes (default 8) and returns at once on green, failed,
or a run that needs approval. A PR also needs its Sonar gate and CodeQL clean: --sonar-key sets
the project key (default <owner>_<repo>), --no-sonar and --no-codeql skip one each. Mergify Merge
Protections and Mergify Merge Queue are ignored.
EOF
}

die() {
  printf 'error\n%s\n' "$*"
  exit 4
}

repo="" pr="" sha="" wait=0 timeout=8 sonar_key="" no_sonar=0 no_codeql=0
while [[ $# -gt 0 ]]; do
  case "$1" in
  --repo)
    repo="${2:-}"
    shift 2
    ;;
  --pr)
    pr="${2:-}"
    shift 2
    ;;
  --sha)
    sha="${2:-}"
    shift 2
    ;;
  --wait)
    wait=1
    shift
    ;;
  --timeout)
    timeout="${2:-}"
    shift 2
    ;;
  --sonar-key)
    sonar_key="${2:-}"
    shift 2
    ;;
  --no-sonar)
    no_sonar=1
    shift
    ;;
  --no-codeql)
    no_codeql=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    die "unknown argument: $1"
    ;;
  esac
done

[[ "${repo}" == */* ]] || {
  usage >&2
  die "--repo <owner/repo> is required"
}
[[ -n "${pr}" || -n "${sha}" ]] || {
  usage >&2
  die "one of --pr or --sha is required"
}
[[ -z "${pr}" || -z "${sha}" ]] || die "--pr and --sha are mutually exclusive"
[[ -z "${pr}" || "${pr}" =~ ^[0-9]+$ ]] || die "--pr must be a number"
[[ -z "${sha}" || "${sha}" =~ ^[0-9a-f]{40}$ ]] || die "--sha must be a full 40-character sha"
[[ "${timeout}" =~ ^[0-9]+$ ]] || die "--timeout must be whole minutes"
sonar_key="${sonar_key:-${repo/\//_}}"

failed=() pending=() not_started=0 approval=0 runs_json="[]"

add() {
  local -n list="$1"
  local line
  while IFS= read -r line; do
    [[ -z "${line}" ]] || list+=("${line}")
  done <<<"$2"
}

record_unfinished() {
  local waiting
  waiting=$(jq -r '.[] | select(.status == "waiting") | "\(.name): waiting, needs approval"' <<<"$1")
  [[ -z "${waiting}" ]] || approval=1
  add pending "${waiting}"
  add pending "$(jq -r '.[] | select(.status != "completed" and .status != "waiting") | "\(.name): \(.status)"' <<<"$1")"
}

record_runs() {
  local runs="$1" count
  count=$(jq 'length' <<<"${runs}")
  if [[ "${count}" -eq 0 ]]; then
    not_started=1
    return
  fi
  record_unfinished "${runs}"
  add failed "$(jq -r '.[] | select(.status == "completed" and (.conclusion | IN("success", "skipped", "neutral") | not)) | "\(.name): \(.conclusion)"' <<<"${runs}")"
}

fetch_runs() {
  runs_json=$(gh run list --commit "$1" --repo "${repo}" --limit 100 --json name,status,conclusion) ||
    die "gh run list failed for $1"
  jq -e . >/dev/null 2>&1 <<<"${runs_json}" || die "gh run list gave no JSON for $1"
}

check_pr() {
  local out rc=0 errfile msg head count
  errfile=$(mktemp)
  out=$(gh pr checks "${pr}" --repo "${repo}" --json name,bucket 2>"${errfile}") || rc=$?
  msg=$(<"${errfile}")
  rm -f "${errfile}"
  if [[ "${msg}" == *"no checks reported"* ]]; then
    out="[]"
  else
    case "${rc}" in
    0 | 1 | 8) ;;
    *) die "gh pr checks exited ${rc}: ${msg:-${out}}" ;;
    esac
    jq -e . >/dev/null 2>&1 <<<"${out}" || die "gh pr checks gave no JSON: ${msg:-${out}}"
  fi

  out=$(jq --argjson ig "${IGNORED_CHECKS}" '[.[] | select(.name | IN($ig[]) | not)]' <<<"${out}")
  count=$(jq '[.[] | select(.name | startswith("Mergify") | not)] | length' <<<"${out}")
  [[ "${count}" -gt 0 ]] || not_started=1
  add failed "$(jq -r '.[] | select(.bucket | IN("pass", "skipping", "pending") | not) | "\(.name): \(.bucket)"' <<<"${out}")"
  add pending "$(jq -r '.[] | select(.bucket == "pending") | "\(.name): pending"' <<<"${out}")"

  if [[ ${#failed[@]} -eq 0 ]]; then
    head=$(gh pr view "${pr}" --repo "${repo}" --json headRefOid | jq -r .headRefOid)
    fetch_runs "${head}"
    record_unfinished "${runs_json}"
  fi
}

check_sonar() {
  local gate total issues_url="https://sonarcloud.io/api/issues/search?componentKeys=${sonar_key}&pullRequest=${pr}&resolved=false"
  gate=$(curl -sS --max-time 20 "https://sonarcloud.io/api/qualitygates/project_status?projectKey=${sonar_key}&pullRequest=${pr}" |
    jq -r '.projectStatus.status // "null"')
  if [[ "${gate}" == "null" ]]; then
    die "no Sonar quality gate for key ${sonar_key} on PR ${pr}: pass the right --sonar-key, or --no-sonar"
  elif [[ "${gate}" != "OK" ]]; then
    failed+=("sonar: quality gate ${gate}")
  else
    total=$(curl -sS --max-time 20 "${issues_url}" |
      jq -r '.total // "null"')
    [[ "${total}" != "null" ]] || die "Sonar issue search returned no total for key ${sonar_key}"
    [[ "${total}" -eq 0 ]] || failed+=("sonar: ${total} open issues: ${issues_url}")
  fi
}

check_codeql() {
  local alerts
  alerts=$(gh api "repos/${repo}/code-scanning/alerts?ref=refs/pull/${pr}/merge&state=open" | jq 'length') ||
    die "CodeQL alerts query failed"
  [[ "${alerts}" -eq 0 ]] || failed+=("codeql: ${alerts} open alerts")
}

check_sha() {
  local runs statuses count
  runs=$(gh api --paginate "repos/${repo}/commits/${sha}/check-runs?per_page=100" | jq -s --argjson ig "${IGNORED_CHECKS}" \
    '[.[].check_runs[] | select(.name | IN($ig[]) | not)]') || die "check-runs query failed"
  count=$(jq 'length' <<<"${runs}")
  [[ "${count}" -gt 0 ]] || not_started=1
  add pending "$(jq -r '.[] | select(.status != "completed") | "\(.name): \(.status)"' <<<"${runs}")"
  add failed "$(jq -r '.[] | select(.status == "completed" and (.conclusion | IN("success", "skipped", "neutral") | not)) | "\(.name): \(.conclusion)"' <<<"${runs}")"

  statuses=$(gh api "repos/${repo}/commits/${sha}/status") || die "commit status query failed"
  jq -e . >/dev/null 2>&1 <<<"${statuses}" || die "commit status query gave no JSON"
  add failed "$(jq -r '.statuses[] | select(.state | IN("failure", "error")) | "\(.context): \(.state)"' <<<"${statuses}")"
  add pending "$(jq -r '.statuses[] | select(.state == "pending") | "\(.context): pending"' <<<"${statuses}")"

  fetch_runs "${sha}"
  record_runs "${runs_json}"
}

evaluate() {
  failed=() pending=() not_started=0 approval=0
  if [[ -n "${pr}" ]]; then
    check_pr
    if [[ ${#failed[@]} -eq 0 && ${#pending[@]} -eq 0 && "${not_started}" -eq 0 ]]; then
      [[ "${no_sonar}" -eq 1 ]] || check_sonar
      [[ "${no_codeql}" -eq 1 ]] || check_codeql
    fi
  else
    check_sha
  fi

  if [[ ${#failed[@]} -gt 0 ]]; then
    state=failed code=1
  elif [[ ${#pending[@]} -gt 0 ]]; then
    state=pending code=2
  elif [[ "${not_started}" -eq 1 ]]; then
    state=not-started code=3
  else
    state=green code=0
  fi
}

budget=$((timeout * 60))
slept=0
start=${SECONDS}
while :; do
  evaluate
  [[ "${wait}" -eq 1 && "${code}" -ge 2 && "${approval}" -eq 0 ]] || break
  elapsed=$((SECONDS - start))
  [[ ${slept} -le ${elapsed} ]] || elapsed=${slept}
  [[ ${elapsed} -lt ${budget} ]] || break
  sleep "${INTERVAL}"
  slept=$((slept + INTERVAL))
done

printf '%s\n' "${state}"
[[ ${#failed[@]} -eq 0 ]] || printf '%s\n' "${failed[@]}"
[[ ${#pending[@]} -eq 0 ]] || printf '%s\n' "${pending[@]}"
exit "${code}"
