# Source Adapter Patch Archive

This directory snapshots the PyStudio patch series carried by the managed
source forks.

- `primary/`: patches currently carried by
  `vg188/pystudio-termux-source-termux`, forked from
  `termux/termux-packages`.
- `secondary/`: patches currently carried by
  `vg188/pystudio-termux-source-pacman`, forked from
  `termux-pacman/termux-packages`.

The active builds clone the managed source forks directly. These patch files
are an audit and recovery aid: if a source fork is rebuilt from a clean upstream
again, replay or cherry-pick the relevant source-side patches and keep CI
workflow logic in the thin toolchain repositories.

Do not add full package trees here. Store only small, reviewable patch series
or notes that describe PyStudio-specific source changes.
