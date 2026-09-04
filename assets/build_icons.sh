#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Generating resources/icon.png from data/logo.png..."
convert data/logo-icon.png -resize 256x256 resources/icon.png

echo "Generating resources/icon-about.png from data/logo.png..."
convert data/logo.png -resize 256x256 resources/icon-about.png

echo "Generating resources/icon.ico from data/logo-icon.png..."
convert data/logo-icon.png -define icon:auto-resize=256,64,48,32,16 resources/icon.ico

echo "Done."
