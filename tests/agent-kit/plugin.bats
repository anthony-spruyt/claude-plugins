#!/usr/bin/env bats
#
# The agent-kit plugin's manifest, hook wiring, shipped scripts and skill hang together.

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
PLUGIN="${REPO_ROOT}/agent-kit"
MARKETPLACE="${REPO_ROOT}/.claude-plugin/marketplace.json"

@test "the marketplace entry points at the plugin directory" {
  [ "$(jq -r '.plugins[] | select(.name == "agent-kit") | .source' "${MARKETPLACE}")" = "./agent-kit" ]
  [ "$(jq -r '.name' "${PLUGIN}/.claude-plugin/plugin.json")" = "agent-kit" ]
}

@test "hooks.json wires exactly the notes events to progress.sh, each with a timeout" {
  events=$(jq -r '.hooks | keys | join(" ")' "${PLUGIN}/hooks/hooks.json")
  [ "${events}" = "PreToolUse SessionEnd SessionStart SubagentStart SubagentStop" ]
  for ev in PreToolUse SessionEnd SessionStart SubagentStart SubagentStop; do
    [ "$(jq -r --arg e "${ev}" '.hooks[$e] | length' "${PLUGIN}/hooks/hooks.json")" -eq 1 ]
    [ "$(jq -r --arg e "${ev}" '.hooks[$e][0].hooks[0].command' "${PLUGIN}/hooks/hooks.json")" = "bash \"\${CLAUDE_PLUGIN_ROOT}/scripts/progress.sh\" ${ev}" ]
    [ "$(jq -r --arg e "${ev}" '.hooks[$e][0].hooks[0].timeout' "${PLUGIN}/hooks/hooks.json")" = "10" ]
  done
}

@test "SessionStart fires only for startup, resume, clear and fork" {
  [ "$(jq -r '.hooks.SessionStart[0].matcher' "${PLUGIN}/hooks/hooks.json")" = "startup|resume|clear|fork" ]
}

@test "the shipped scripts are executable and resolve by bare name with the plugin bin after the user's PATH" {
  for s in workspace.sh push-reviewed.sh ci-status.sh; do
    [ -x "${PLUGIN}/bin/${s}" ]
    [ "$(PATH="/usr/local/bin:/usr/bin:/bin:${PLUGIN}/bin" bash -c "command -v ${s}")" = "${PLUGIN}/bin/${s}" ]
  done
  [ -x "${PLUGIN}/scripts/progress.sh" ]
}

@test "the writing-agents skill ships and names nothing from one repo" {
  [ -f "${PLUGIN}/skills/writing-agents/SKILL.md" ]
  [ "$(sed -n 's/^name: //p' "${PLUGIN}/skills/writing-agents/SKILL.md")" = "writing-agents" ]
  run grep -rniE "for this project|this project|this harness|auto memory|n8n|spruyt|cluster|flux|renovate|talos|etcd|qa-validator|cluster-validator|chore-runner|renovate-pr-analyzer|workspace\.sh|Explore\.md|\.claude/scripts" "${PLUGIN}/skills"
  [ "${status}" -eq 1 ]
  grep -q "Plugin agents" "${PLUGIN}/skills/writing-agents/references/agent-frontmatter.md"
}
