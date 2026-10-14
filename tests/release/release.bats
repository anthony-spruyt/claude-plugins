#!/usr/bin/env bats
#
# release-please owns plugin versions: one package per marketplace plugin, writing plugin.json.

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
MARKETPLACE="${REPO_ROOT}/.claude-plugin/marketplace.json"
CONFIG="${REPO_ROOT}/release-please-config.json"
MANIFEST="${REPO_ROOT}/.release-please-manifest.json"

setup() {
  dirs=$(jq -er '.plugins[].source | ltrimstr("./")' "${MARKETPLACE}" | sort)
  [ -n "${dirs}" ]
}

@test "marketplace entries carry no version, so plugin.json is the only one" {
  [ "$(jq '[.plugins[] | select(has("version"))] | length' "${MARKETPLACE}")" -eq 0 ]
}

@test "every marketplace plugin is a release-please package that writes its plugin.json version" {
  [ "${dirs}" = "$(jq -r '.packages | keys[]' "${CONFIG}" | sort)" ]
  [ "$(jq -r '.["release-type"]' "${CONFIG}")" = "simple" ]
  [ "$(jq -c '.["extra-files"]' "${CONFIG}")" = '[{"type":"json","path":".claude-plugin/plugin.json","jsonpath":"$.version"}]' ]
  [ "$(jq '[.packages[] | select(has("release-type") or has("extra-files"))] | length' "${CONFIG}")" -eq 0 ]
}

@test "the release manifest lists every plugin at its plugin.json version" {
  [ "${dirs}" = "$(jq -r 'keys[]' "${MANIFEST}" | sort)" ]
  for dir in ${dirs}; do
    version=$(jq -er '.version' "${REPO_ROOT}/${dir}/.claude-plugin/plugin.json")
    [ "$(jq -r --arg d "${dir}" '.[$d]' "${MANIFEST}")" = "${version}" ]
  done
}

@test "only feat, fix, perf and revert commits cut a release" {
  [ "$(jq -r '[.["changelog-sections"][] | select(.hidden != true) | .type] | sort | join(" ")' "${CONFIG}")" = "feat fix perf revert" ]
}
