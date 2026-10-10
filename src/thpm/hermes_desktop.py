"""Local Hermes Desktop theme contributions, independent of gateway skins."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .paths import Paths

PLUGIN_ID = "thpm-local-omarchy"
THEME_NAME = "thpm-local-omarchy"


def target(paths: Paths) -> Path:
    return paths.home / ".hermes/desktop-plugins" / PLUGIN_ID / "plugin.js"


def readiness(paths: Paths) -> tuple[bool, str]:
    root = paths.home / ".hermes/hermes-agent/apps/desktop/release/linux-unpacked/resources/app.asar.unpacked/dist"
    main = root / "electron-main.mjs"
    try:
        if not main.is_file() or "hermes:fs:desktopPluginsRoot" not in main.read_text():
            return False, "Hermes Desktop build with local runtime-plugin support is required"
        # Verify the shipped renderer, not an adjacent source checkout. The
        # theme registry and plugin-loader capabilities must both be present.
        required = {"hermes-desktop-user-themes-v1", "@hermes/plugin-sdk"}
        for bundle in (root / "assets").glob("*.js"):
            content = bundle.read_text()
            required = {marker for marker in required if marker not in content}
            if not required:
                break
        if required:
            return False, "Hermes Desktop renderer lacks the theme/runtime-plugin contract"
        # Desktop's local filesystem profile is separate from the agent's
        # active_profile and from the connected remote gateway's profile.
        profile_file = paths.config_home / "Hermes/active-profile.json"
        if profile_file.is_file():
            preference = json.loads(profile_file.read_text())
            profile = preference.get("profile") if isinstance(preference, dict) else None
            if isinstance(profile, str) and profile.strip() not in {"", "default"}:
                return False, "local desktop theme currently supports the default local Hermes profile only"
        destination = target(paths)
        if destination.parent.resolve() != destination.parent:
            return False, "local Hermes Desktop plugin directory is redirected"
    except (OSError, ValueError) as exc:
        return False, f"cannot verify local Hermes Desktop capabilities: {exc}"
    return True, "local runtime-plugin/theme support verified; desktop selection remains user-owned"


def theme(p: dict[str, str]) -> dict[str, object]:
    accent = p.get("accent", p["blue"])
    colors = {
        "background": p["bg"], "foreground": p["fg"],
        "card": p["dark_bg"], "cardForeground": p["fg"],
        "muted": p["lighter_bg"], "mutedForeground": p["muted"],
        "popover": p["dark_bg"], "popoverForeground": p["fg"],
        "primary": accent, "primaryForeground": p["bg"],
        "secondary": p["lighter_bg"], "secondaryForeground": p["fg"],
        "accent": p["selection"], "accentForeground": p["fg"],
        "border": p["lighter_bg"], "input": p["lighter_bg"],
        "ring": accent, "midground": accent, "composerRing": accent,
        "destructive": p["red"], "destructiveForeground": p["bg"],
        "sidebarBackground": p["darker_bg"], "sidebarBorder": p["lighter_bg"],
        "userBubble": p["lighter_bg"], "userBubbleBorder": p["selection"],
    }
    terminal = {
        "foreground": p["fg"], "cursor": p.get("cursor", p["fg"]),
        "selectionBackground": p.get("selection_background", p["selection"]),
        "black": p["dark_bg"], "white": p["light_fg"],
        "brightBlack": p["muted"], "brightWhite": p["bright_fg"],
    }
    for color in ("red", "green", "yellow", "blue", "magenta", "cyan"):
        terminal[color] = p[color]
        terminal["bright" + color.capitalize()] = p["bright_" + color]
    return {
        "name": THEME_NAME, "label": "Local Omarchy",
        "description": "THPM · local desktop palette; independent of the remote agent",
        # Both slots intentionally equal: follow Omarchy's own light/dark palette,
        # never Hermes' synthesized variant of that palette.
        "colors": colors, "darkColors": colors,
        "terminal": terminal, "darkTerminal": terminal,
    }


def render(palette: dict[str, str]) -> str:
    data = json.dumps(theme(palette), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(data.encode()).hexdigest()
    # Plain, self-contained ESM through Hermes' documented runtime-plugin door.
    # No gateway RPC, Electron bundle patches, selection writes, DOM
    # styling, timers that survive unload, or hidden remote-backend mutation.
    return (
        "// THPM-owned local Hermes Desktop theme contribution\n"
        f"const theme = {data};\n"
        "export default {\n"
        f"  id: {json.dumps(PLUGIN_ID)}, name: 'Local Omarchy (THPM)',\n"
        "  description: 'Follow the local Omarchy palette when Local Omarchy is selected',\n"
        "  defaultEnabled: true,\n"
        "  register(ctx) {\n"
        "    ctx.register({id: 'palette', area: 'themes', data: theme});\n"
        f"    ctx.storage.set('registration', {{fingerprint: '{digest}', registeredAt: new Date().toISOString()}});\n"
        f"    console.info('[thpm-local-omarchy] registered palette {digest}');\n"
        "    let timer, previous;\n"
        "    const report = () => {\n"
        "      const css = getComputedStyle(document.documentElement);\n"
        "      const selected = document.documentElement.dataset.hermesTheme === theme.name;\n"
        "      const background = css.getPropertyValue('--theme-background-seed').trim();\n"
        "      const foreground = css.getPropertyValue('--theme-foreground').trim();\n"
        "      const state = JSON.stringify({selected, background, foreground, expectedBackground: theme.colors.background, expectedForeground: theme.colors.foreground});\n"
        "      if (state !== previous) {\n"
        "        ctx.storage.set('consumption', {...JSON.parse(state), observedAt: new Date().toISOString()});\n"
        "        console.info('[thpm-local-omarchy] consumption', state);\n"
        "      }\n"
        "      previous = state;\n"
        "    };\n"
        "    const schedule = () => { clearTimeout(timer); timer = setTimeout(report, 200); };\n"
        "    const observer = new MutationObserver(schedule);\n"
        "    observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-hermes-theme', 'style']});\n"
        "    schedule();\n"
        "    ctx.onDispose(() => { clearTimeout(timer); observer.disconnect(); });\n"
        "  }\n"
        "};\n"
    )
