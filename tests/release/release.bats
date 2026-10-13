#!/usr/bin/env bats
#
# release-please owns plugin versions: one package per marketplace plugin, writing plugin.json.

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
MARKETPLACE="${REPO_ROOT}/.claude-plugin/marketplace.json"
CONFIG="${REPO_ROOT}/release-please-config.json"
MANIFEST="${REPO_ROOT}/.release-please-manifest.json"

plugin_dirs() {
  jq -r '.plugins[].source | ltrimstr("./")' "${MARKETPLACE}"
}

@test "marketplace entries carry no version, so plugin.json is the only one" {
  [ "$(jq '[.plugins[] | select(has("version"))] | length' "${MARKETPLACE}")" -eq 0 ]
}

@test "every marketplace plugin is a release-please package that writes its plugin.json version" {
  [ "$(plugin_dirs | sort)" = "$(jq -r '.packages | keys[]' "${CONFIG}" | sort)" ]
  for dir in $(plugin_dirs); do
    [ "$(jq -r --arg d "${dir}" '.packages[$d]["release-type"]' "${CONFIG}")" = "simple" ]
    [ "$(jq -c --arg d "${dir}" '.packages[$d]["extra-files"]' "${CONFIG}")" = '[{"type":"json","path":".claude-plugin/plugin.json","jsonpath":"$.version"}]' ]
  done
}

@test "the release manifest matches each plugin.json version" {
  for dir in $(plugin_dirs); do
    version=$(jq -r '.version' "${REPO_ROOT}/${dir}/.claude-plugin/plugin.json")
    [ -n "${version}" ]
    [ "$(jq -r --arg d "${dir}" '.[$d]' "${MANIFEST}")" = "${version}" ]
  done
}

@test "releases publish instead of waiting as drafts" {
  [ "$(jq -r '.draft' "${CONFIG}")" = "false" ]
}
