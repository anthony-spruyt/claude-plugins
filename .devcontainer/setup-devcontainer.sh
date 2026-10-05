#!/bin/bash
set -euo pipefail

# Keep in sync with the "Install Python dependencies" step in .github/workflows/ci.yaml
pip install --no-cache-dir pytest pyyaml
