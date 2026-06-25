#!/usr/bin/env bash
set -euo pipefail

df -h

echo "Largest pre-cleanup directories:"
sudo du -xh -d 1 /usr /opt /mnt 2>/dev/null | sort -h | tail -40 || true

sudo rm -rf /usr/share/dotnet || true
sudo rm -rf /usr/local/lib/android || true
sudo rm -rf /opt/ghc || true
sudo rm -rf /opt/hostedtoolcache || true
sudo rm -rf /opt/az || true
sudo rm -rf /usr/local/share/boost || true
sudo rm -rf /usr/local/share/chromium || true
sudo rm -rf /usr/local/.ghcup || true
sudo rm -rf /usr/share/swift || true
sudo apt-get clean || true
docker system prune -af || true

echo "Largest post-cleanup directories:"
sudo du -xh -d 1 /usr /opt /mnt 2>/dev/null | sort -h | tail -40 || true

df -h
