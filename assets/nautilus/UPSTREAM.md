# Upstream provenance

The Nautilus extension in this directory is adapted from
[`JJDizz1L/paint-omarchy-nautilus`](https://github.com/JJDizz1L/paint-omarchy-nautilus),
pinned at commit `7324544a1dad9602d1c3195df3c984ed2223750a` (commit author
`JJDizz1L <jjdizz1l@proton.me>`).

THPM retains the upstream MIT notice in `LICENSE`. The extension was adapted to
use THPM's XDG-aware cache path and single theme hook. THPM independently owns
the transactional installation, palette rendering, readiness diagnostics, and
reversible GNOME accent lifecycle around the adapted extension.

THPM does not install or execute the upstream hook scripts, installer, package
bootstrap, or privilege/package-management commands.
