#!/usr/bin/env bash
set -euo pipefail

df -h

sudo rm -rf /usr/share/dotnet || true
sudo rm -rf /usr/local/lib/android || true
sudo rm -rf /opt/ghc || true
sudo rm -rf /usr/local/share/boost || true
sudo apt-get clean || true
docker system prune -af || true

df -h

