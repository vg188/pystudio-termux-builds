#!/usr/bin/env bash
set -euo pipefail

size="${1:-16G}"
swapfile="/mnt/pystudio-swapfile"

if swapon --show=NAME --noheadings | grep -Fxq "$swapfile"; then
  sudo swapoff "$swapfile"
fi

sudo rm -f "$swapfile"
if ! sudo fallocate -l "$size" "$swapfile"; then
  megabytes="${size%G}"
  sudo dd if=/dev/zero of="$swapfile" bs=1M count="$((megabytes * 1024))" status=progress
fi

sudo chmod 600 "$swapfile"
sudo mkswap "$swapfile"
sudo swapon "$swapfile"
free -h
swapon --show

