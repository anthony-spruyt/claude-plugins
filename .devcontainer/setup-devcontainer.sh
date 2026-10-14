#!/bin/bash
set -euo pipefail

# Keep in sync with .github/ci-requirements.txt
pip install --no-cache-dir --only-binary :all: pytest pytest-xdist pyyaml
