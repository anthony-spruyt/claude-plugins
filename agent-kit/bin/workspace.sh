#!/usr/bin/env bash
# Usage: workspace.sh <owner/repo> <task-name>
# Clones the repo into its own directory on a new branch named after the task; prints the path.
# Runs `pre-commit install` in the clone when the repo has a .pre-commit-config.yaml (stderr only; failure only warns).
# AGENT_WORKSPACE_ROOT and AGENT_WORKSPACE_REMOTE_BASE override the parent directory and clone URL prefix.
set -euo pipefail

usage() {
  echo "Usage: workspace.sh <owner/repo> <task-name>" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
repo=$1
task=$2

[[ "$repo" =~ ^[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*$ ]] || {
  echo "workspace.sh: repo must look like owner/repo, got '$repo'" >&2
  exit 2
}
[[ "$task" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] || {
  echo "workspace.sh: task name must be a lowercase slug (a-z, 0-9, -; at most 40 characters), got '$task'" >&2
  exit 2
}

root=${AGENT_WORKSPACE_ROOT:-/tmp/agent-work}
base=${AGENT_WORKSPACE_REMOTE_BASE:-git@github.com:}

mkdir -p "$root"
dir=$(mktemp -d "$root/${repo##*/}-${task}-XXXX")
trap 'rm -rf -- "$dir"' ERR

git clone --quiet "${base}${repo}.git" "$dir" >&2
git -C "$dir" switch --quiet -c "$task" >&2

trap - ERR

# A missing or failing install must never fail the clone: the caller captures the path from stdout
if [[ -f "$dir/.pre-commit-config.yaml" ]]; then
  if ! pc=$(command -v pre-commit 2>/dev/null); then
    echo "workspace.sh: warning: pre-commit not found, so commits in $dir skip its hook" >&2
  else
    # Absolute path, resolved before the cd, so PATH is never searched from inside the clone
    [[ "$pc" == /* ]] || pc=$PWD/${pc#./}
    if ! (cd "$dir" && "$pc" install) >&2; then
      echo "workspace.sh: warning: 'pre-commit install' failed, so commits in $dir skip its hook" >&2
    fi
  fi
fi

echo "$dir"
