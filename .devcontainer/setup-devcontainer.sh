#!/bin/bash
set -euo pipefail

# Keep in sync with the "Install bats" step in .github/workflows/ci.yaml
install_bats() {
  sudo apt-get update -qq && sudo apt-get install -y -qq bats
  for lib in bats-support bats-assert; do
    dest="/usr/local/lib/bats/${lib}"
    [[ -d "${dest}" ]] && continue
    sudo git clone --depth 1 --branch v0.3.0 "https://github.com/bats-core/${lib}.git" "${dest}"
  done
  sudo chmod -R a+r /usr/local/lib/bats
}

install_bats || echo "WARNING: bats install failed; bats tests/hooks/ will not run"
