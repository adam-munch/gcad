#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

"${PYTHON:-python}" assets/build_icons.py
