"""Local Hermes Desktop theme contributions, independent of gateway skins."""
from __future__ import annotations

import hashlib
import json
import math
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


def _rgb(value: str) -> tuple[int, ...]:
    # The palette loader has already validated six-digit hex colors.
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _mix(a: str, b: str, amount: float) -> str:
    # Match Hermes's sRGB mix / JS Math.round, not Python's ties-to-even round.
    channels = (math.floor(x + (y - x) * amount + 0.5) for x, y in zip(_rgb(a), _rgb(b)))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _luminance(value: str, *, relative: bool = False) -> float:
    channels = [channel / 255 for channel in _rgb(value)]
    if relative:
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(channels, (0.2126, 0.7152, 0.0722)))


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a, relative=True), _luminance(b, relative=True)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _readable_on(background: str) -> str:
    return "#ffffff" if _contrast(background, "#ffffff") >= _contrast(background, "#161616") else "#161616"


def _ensure_contrast(color: str, background: str) -> str:
    if _contrast(color, background) >= 4.5:
        return color
    towards = "#ffffff" if _luminance(background, relative=True) < 0.5 else "#000000"
    for step in range(1, 6):
        best = _mix(color, towards, step / 5)
        if _contrast(best, background) >= 4.5:
            return best
    return best


def theme(p: dict[str, str]) -> dict[str, object]:
    # Mirror Hermes themes/skin.ts's skinToDesktopTheme with the seeds supplied
    # by Omarchy's hermes.yaml.tpl. Never use terminal dark_bg/darker_bg as GUI
    # surfaces: those may be dark even in an authored light palette.
    background, foreground = p["bg"], p["fg"]
    dark = _luminance(background) < 0.4
    sidebar = _mix(background, foreground, 0.02 if dark else 0.012)
    accent = _ensure_contrast(p.get("accent", p["blue"]), sidebar)
    border = p["muted"]
    colors = {
        "background": background, "foreground": foreground,
        "card": _mix(background, foreground, 0.04 if dark else 0.025), "cardForeground": foreground,
        "muted": _mix(background, foreground, 0.06 if dark else 0.04), "mutedForeground": p["dark_fg"],
        "popover": _mix(background, foreground, 0.08 if dark else 0.05), "popoverForeground": foreground,
        "primary": accent, "primaryForeground": _readable_on(accent),
        "secondary": _mix(accent, background, 0.72 if dark else 0.86), "secondaryForeground": foreground,
        "accent": _mix(accent, background, 0.82 if dark else 0.88), "accentForeground": foreground,
        "border": border, "input": p["lighter_bg"],
        "ring": accent, "midground": accent, "midgroundForeground": _readable_on(accent), "composerRing": accent,
        "destructive": p["red"], "destructiveForeground": _readable_on(p["red"]),
        "sidebarBackground": sidebar, "sidebarBorder": border,
        "userBubble": _mix(background, accent, 0.18 if dark else 0.12), "userBubbleBorder": border,
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
