# Source Adapter Patch Archive

This directory stores PyStudio source-side patch queues used by the main
orchestrator at build time.

- `primary/`: patches currently carried by
  `vg188/pystudio-termux-source-termux`, forked from
  `termux/termux-packages`.
- `secondary/`: patches currently carried by
  `vg188/pystudio-termux-source-pacman`, forked from
  `termux-pacman/termux-packages`.

The active builds clone the configured upstream package tree, then apply the
patches listed in that source's `series` file. Patch files that are not listed
in `series` are historical audit material only.

The managed source forks are kept as clean upstream mirrors. Do not commit
PyStudio-specific patches to the source forks; add or update patch files here
instead. If upstream absorbs a fix, remove it from `series` and keep the old
patch file only as history when useful.

Do not add full package trees here. Store only small, reviewable patch series
or notes that describe PyStudio-specific source changes.
