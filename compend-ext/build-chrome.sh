#!/bin/sh
# Assemble the Chrome version into ./chrome (same code, Chrome manifest).
# Re-run after editing background.js / content.js, then hit "reload" on
# chrome://extensions.
cd "$(dirname "$0")"
rm -rf chrome && mkdir -p chrome/icons
cp background.js content.js welcome.html welcome.js chrome/
cp icons/*.png chrome/icons/
cp manifest.chrome.json chrome/manifest.json
echo "Built $(pwd)/chrome"
