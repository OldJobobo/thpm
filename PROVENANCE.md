# Provenance

`thpm` was independently authored as a clean implementation against the public Omarchy 4.x command, theme-template, hook, and shell-plugin interfaces.

The earlier `imbypass/omarchy-theme-hook` project motivated the general problem—applying a desktop theme to software outside Omarchy—but its unlicensed implementation is not incorporated here. This repository has fresh source code, tests, documentation, UI, packaging, naming, state format, plugin registry, and Git history. Migration recognizes old hook filenames only as external data and never imports or executes their contents.

`assets/vencord/thpm-midnight.css` is a deliberate licensed exception to the clean implementation: it redistributes and adapts the compiled Midnight Discord theme from `refact0r/midnight-discord` under that project's MIT License. The upstream commit and artifact are recorded in `assets/vencord/UPSTREAM.md`, and the required copyright and permission notice is retained in `assets/vencord/LICENSE.midnight`.

`assets/nautilus/omarchy_palette.py` is adapted from `JJDizz1L/paint-omarchy-nautilus` at pinned commit `7324544a1dad9602d1c3195df3c984ed2223750a`, authored by `JJDizz1L <jjdizz1l@proton.me>`. It is redistributed under the upstream MIT License with the copyright and permission notice retained in `assets/nautilus/LICENSE`; adaptation details are recorded in `assets/nautilus/UPSTREAM.md`. THPM does not redistribute or execute the upstream installer, package bootstrap, or theme hook scripts.

Omarchy names and interfaces remain the property of their respective project and contributors. Optional application names identify interoperability targets only.
