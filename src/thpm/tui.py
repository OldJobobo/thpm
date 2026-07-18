from __future__ import annotations

import asyncio
import tomllib
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, ContentSwitcher, Footer, Input, Label, Link, ListItem, ListView, Static, Switch

from . import __version__
from .omarchy import run
from .palette import HEX, load as load_palette
from .paths import Paths
from .service import Service


SECTIONS = ("overview", "integrations", "doctor", "system")
DONATE_URL = "https://ko-fi.com/oldjobobo"
SECTION_TITLES = {
    "overview": ("Overview", "Your theme integration control center"),
    "integrations": ("Integrations", "Manage optional application theme integrations"),
    "doctor": ("Doctor", "Configuration health and integration diagnostics"),
    "system": ("System", "Theme lifecycle, updates, and maintenance"),
}


def omarchy_theme(paths: Paths) -> tuple[Theme, str | None]:
    """Build a Textual theme from the active Omarchy semantic palette."""
    try:
        palette_path = paths.current_theme / "colors.toml"
        palette = load_palette(palette_path)
        source = tomllib.loads(palette_path.read_text())
        explicit_border = str(source.get("active_border_color", ""))
        border = explicit_border if HEX.fullmatch(explicit_border) else palette["lighter_bg"]
        if border.lower() == palette["bg"].lower():
            border = palette["muted"]
        theme = Theme(
            name="thpm-omarchy",
            primary=palette["blue"],
            secondary=palette["magenta"],
            warning=palette["yellow"],
            error=palette["red"],
            success=palette["green"],
            accent=palette["cyan"],
            foreground=palette["fg"],
            background=palette["bg"],
            surface=palette["dark_bg"],
            panel=palette["darker_bg"],
            dark=palette["mode"] == "dark",
            variables={
                "thpm-muted": palette["muted"],
                "thpm-border": border,
                "thpm-bright": palette["bright_fg"],
            },
        )
        return theme, None
    except (OSError, ValueError) as exc:
        return Theme(
            name="thpm-fallback",
            primary="#7aa2f7",
            secondary="#bb9af7",
            warning="#e0af68",
            error="#f7768e",
            success="#9ece6a",
            accent="#7dcfff",
            foreground="#c0caf5",
            background="#1a1b26",
            surface="#24283b",
            panel="#16161e",
            dark=True,
            variables={
                "thpm-muted": "#565f89",
                "thpm-border": "#414868",
                "thpm-bright": "#c0caf5",
            },
        ), f"Active Omarchy palette unavailable; using fallback colors ({exc})"


class ConfirmUpdate(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current: str, available: str) -> None:
        super().__init__()
        self.current = current
        self.available = available

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-card"):
            yield Label("Update THPM?", id="confirm-title")
            yield Static(f"Update THPM from {self.current} to {self.available}?")
            with Horizontal(id="confirm-actions"):
                yield Button("Cancel", id="cancel-update")
                yield Button("Update", id="confirm-update", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#confirm-update", Button).focus()

    @on(Button.Pressed, "#cancel-update")
    def cancel_button(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-update")
    def confirm_button(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmPlugin(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-card"):
            yield Label(f"Enable {self.label}?", id="confirm-title")
            yield Static("This integration changes sensitive application configuration.")
            with Horizontal(id="confirm-actions"):
                yield Button("Cancel", id="cancel-plugin")
                yield Button("Enable", id="confirm-plugin", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#confirm-plugin", Button).focus()

    @on(Button.Pressed, "#cancel-plugin")
    def cancel_button(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-plugin")
    def confirm_button(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PluginRow(ListItem):
    """Focusable integration row with a terminal-native toggle."""

    def __init__(self, plugin: dict[str, object]) -> None:
        super().__init__(name=str(plugin["label"]), id="plugin-" + str(plugin["id"]))
        self.plugin = plugin

    def compose(self) -> ComposeResult:
        ownership = str(self.plugin["ownership"])
        available = bool(self.plugin["available"])
        warnings = list(self.plugin.get("warnings", []))
        if ownership == "native":
            prefix = "Managed by Omarchy · "
        elif warnings:
            prefix = "Needs attention · "
        elif not available:
            prefix = "Not actionable · "
        else:
            prefix = ""
        with Horizontal(classes="plugin-row-inner"):
            with Vertical(classes="plugin-copy"):
                yield Label(str(self.plugin["label"]), classes="plugin-label")
                yield Static(prefix + str(self.plugin["description"]), classes="plugin-description")
            yield Static(ownership, classes="ownership")
            yield Switch(
                value=bool(self.plugin["enabled"]),
                disabled=ownership == "native" or (not available and not bool(self.plugin["enabled"])),
                id="switch-" + str(self.plugin["id"]),
            )

    @property
    def mutable(self) -> bool:
        return str(self.plugin["ownership"]) != "native" and (
            bool(self.plugin["available"]) or bool(self.plugin["enabled"])
        )


class ThpmTui(App[None]):
    CSS_PATH = "tui.tcss"
    TITLE = "THPM"
    SUB_TITLE = "Theme control"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("1", "section('overview')", "Overview", show=False),
        Binding("2", "section('integrations')", "Integrations", show=False),
        Binding("3", "section('doctor')", "Doctor", show=False),
        Binding("4", "section('system')", "System", show=False),
        Binding("slash", "search", "Search"),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_plugin", "Toggle"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("escape", "escape", "Back", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: Service | None = None, paths: Paths | None = None) -> None:
        self.paths = paths or Paths.discover()
        theme, palette_warning = omarchy_theme(self.paths)
        super().__init__()
        self.register_theme(theme)
        self.theme = theme.name
        self.service = service or Service(self.paths)
        self.section = "overview"
        self.plugins: list[dict[str, object]] = []
        self.counts: dict[str, int] = {key: 0 for key in ("enabled", "disabled", "native", "unavailable", "attention")}
        self.doctor_has_run = False
        self.update_info: dict[str, object] = {"status": "idle", "currentVersion": __version__, "availableVersion": None}
        self.menu_surface = "gui"
        self.palette_warning = palette_warning

    def compose(self) -> ComposeResult:
        yield Static("THPM needs at least an 80 × 24 terminal. Resize the window to continue.", id="too-small")
        with Horizontal(id="app-shell"):
            with Vertical(id="sidebar"):
                yield Static("󰏘  THPM", id="brand")
                yield Static("Theme control", id="brand-subtitle")
                yield Button("1  Overview", id="nav-overview", classes="nav selected")
                yield Button("2  Integrations", id="nav-integrations", classes="nav")
                yield Button("3  Doctor", id="nav-doctor", classes="nav")
                yield Button("4  System", id="nav-system", classes="nav")
                yield Static("", id="sidebar-spacer")
                yield Static("All systems ready", id="sidebar-health")
                yield Static(f"Version {__version__}", id="sidebar-version")
            with Vertical(id="main"):
                with Horizontal(id="topbar"):
                    with Vertical(id="heading"):
                        yield Label("Overview", id="section-title")
                        yield Static(SECTION_TITLES["overview"][1], id="section-subtitle")
                    yield Button("Refresh", id="refresh", classes="top-action")
                    yield Button("Updates", id="header-update", classes="top-action")
                    yield Button("Close", id="close", classes="top-action")
                yield Static("Loading integrations…", id="message")
                with ContentSwitcher(initial="overview", id="sections"):
                    with VerticalScroll(id="overview"):
                        with Grid(id="metrics"):
                            yield self.metric("ACTIVE", "0", "THPM integrations enabled", "active")
                            yield self.metric("HEALTH", "Ready", "no integration warnings", "health")
                            yield self.metric("OMARCHY", "0", "native integrations tracked", "native")
                            yield self.metric("UNAVAILABLE", "0", "optional apps not installed", "unavailable")
                        yield Label("Quick actions", classes="section-label")
                        with Horizontal(classes="action-row"):
                            yield Button("Manage integrations", id="manage-integrations")
                            yield Button("Run Doctor", id="overview-doctor")
                            yield Button("Apply theme", id="overview-apply")
                    with Vertical(id="integrations"):
                        yield Input(placeholder="Search integrations", id="integration-search")
                        yield Static("", id="integration-summary")
                        yield ListView(id="plugin-list")
                        yield Static("No matching integrations", id="no-integrations")
                    with Vertical(id="doctor"):
                        with Horizontal(classes="section-toolbar"):
                            with Vertical(classes="toolbar-copy"):
                                yield Label("Run Doctor to check your setup", id="doctor-summary")
                                yield Static("Checks Omarchy, palette, commands, assets, and plugin warnings", id="doctor-detail")
                            yield Button("Run Doctor", id="run-doctor")
                        yield VerticalScroll(id="doctor-results")
                    with VerticalScroll(id="system"):
                        yield Label("Theme actions", classes="section-label")
                        with Horizontal(classes="action-row"):
                            yield Button("Apply active theme", id="system-apply")
                            yield Button("Reconcile integrations", id="system-reconcile")
                        yield Static("", id="system-message")
                        yield Static("", classes="rule")
                        with Horizontal(classes="system-row"):
                            with Vertical(classes="toolbar-copy"):
                                yield Label("Menu launcher", classes="section-label")
                                yield Static("Omarchy Menu opens the graphical window", id="menu-surface-detail")
                            yield Button("GUI", id="menu-surface-gui", classes="surface-choice selected")
                            yield Button("TUI", id="menu-surface-tui", classes="surface-choice")
                        yield Static("", id="menu-surface-message")
                        yield Static("", classes="rule")
                        with Horizontal(classes="system-row"):
                            with Vertical(classes="toolbar-copy"):
                                yield Label("Updates", classes="section-label")
                                yield Static(f"Installed version {__version__}", id="update-detail")
                            yield Button("Check now", id="update-action")
                            yield Button("Restart shell", id="restart-shell")
                        yield Static("", id="update-message")
                        yield Static("", classes="rule")
                        yield Label("About", classes="section-label")
                        yield Static(
                            "THPM manages optional Omarchy theme integrations. Native integrations remain read-only, "
                            "and every state change uses THPM's shared service layer.",
                            id="about",
                        )
        with Horizontal(id="footer-bar"):
            yield Footer()
            yield Link("Donate on Ko-fi", url=DONATE_URL, id="donate-link")

    @staticmethod
    def metric(title: str, value: str, detail: str, name: str) -> Vertical:
        return Vertical(
            Static(title, classes="metric-title"),
            Static(value, id=f"metric-{name}", classes="metric-value"),
            Static(detail, id=f"metric-{name}-detail", classes="metric-detail"),
            classes="metric",
        )

    def on_mount(self) -> None:
        self.load_state()
        self.check_update(False)
        self.query_one("#restart-shell", Button).display = False

    def apply_omarchy_theme(self) -> None:
        theme, warning = omarchy_theme(self.paths)
        self.register_theme(theme)
        self.theme = theme.name
        self.palette_warning = warning
        self.refresh_css(animate=False)

    @on(Resize)
    def resize_layout(self, event: Resize) -> None:
        self.set_class(event.size.width < 100, "compact")
        self.set_class(event.size.width < 80 or event.size.height < 24, "too-small")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.focused, Input) and action in {"cursor_down", "cursor_up", "toggle_plugin"}:
            return False
        if action in {"cursor_down", "cursor_up", "toggle_plugin"} and self.section != "integrations":
            return False
        return True

    def action_section(self, section: str) -> None:
        self.show_section(section)

    def show_section(self, section: str) -> None:
        if section not in SECTIONS:
            return
        self.section = section
        self.query_one("#sections", ContentSwitcher).current = section
        title, subtitle = SECTION_TITLES[section]
        self.query_one("#section-title", Label).update(title)
        if section == "integrations":
            subtitle = f"{self.counts['enabled']} enabled · {self.counts['native']} handled by Omarchy"
        self.query_one("#section-subtitle", Static).update(subtitle)
        for name in SECTIONS:
            self.query_one(f"#nav-{name}", Button).set_class(name == section, "selected")
        if section == "doctor" and not self.doctor_has_run:
            self.run_doctor()

    def action_search(self) -> None:
        self.show_section("integrations")
        self.query_one("#integration-search", Input).focus()

    def action_refresh(self) -> None:
        self.apply_omarchy_theme()
        self.load_state()
        if self.section == "doctor" and self.doctor_has_run:
            self.run_doctor()

    def action_cursor_down(self) -> None:
        self.query_one("#plugin-list", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#plugin-list", ListView).action_cursor_up()

    def action_toggle_plugin(self) -> None:
        plugin_list = self.query_one("#plugin-list", ListView)
        row = plugin_list.highlighted_child
        if isinstance(row, PluginRow):
            self.toggle_row(row)

    def action_escape(self) -> None:
        search = self.query_one("#integration-search", Input)
        if self.focused is search:
            if search.value:
                search.value = ""
            else:
                self.query_one("#nav-integrations", Button).focus()
            return
        self.exit()

    @on(Button.Pressed, ".nav")
    def nav_pressed(self, event: Button.Pressed) -> None:
        self.show_section(event.button.id.removeprefix("nav-"))

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id in {"refresh"}:
            self.action_refresh()
        elif button_id == "close":
            self.exit()
        elif button_id == "manage-integrations":
            self.show_section("integrations")
        elif button_id == "overview-doctor":
            self.show_section("doctor")
        elif button_id == "run-doctor":
            self.run_doctor()
        elif button_id in {"overview-apply", "system-apply"}:
            self.run_system_action("apply")
        elif button_id == "system-reconcile":
            self.run_system_action("reconcile")
        elif button_id in {"header-update", "update-action"}:
            if self.update_info.get("status") == "available":
                self.confirm_update()
            else:
                self.check_update(True)
        elif button_id == "restart-shell":
            self.restart_shell()
        elif button_id.startswith("menu-surface-"):
            self.set_menu_surface(button_id.removeprefix("menu-surface-"))

    @on(Input.Changed, "#integration-search")
    async def search_changed(self, event: Input.Changed) -> None:
        await self.render_plugins(event.value)

    @on(ListView.Selected, "#plugin-list")
    def plugin_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, PluginRow):
            self.toggle_row(event.item)

    @on(Switch.Changed)
    def switch_changed(self, event: Switch.Changed) -> None:
        row = event.switch.parent.parent
        if isinstance(row, PluginRow) and row.mutable and bool(row.plugin["enabled"]) != event.value:
            plugin_id = str(row.plugin["id"])
            if event.value and bool(row.plugin.get("confirmationRequired")):
                self.push_screen(ConfirmPlugin(str(row.plugin["label"])),
                    lambda confirmed: self.plugin_confirmed(plugin_id, bool(confirmed)))
            else:
                self.set_plugin(plugin_id, event.value)

    def toggle_row(self, row: PluginRow) -> None:
        if not row.mutable:
            self.notify("This integration is read-only or unavailable.", severity="warning")
            return
        switch = row.query_one(Switch)
        switch.value = not switch.value

    @work(exclusive=True, group="state", exit_on_error=False)
    async def load_state(self) -> None:
        self.set_message("Loading integrations…")
        try:
            payload = await asyncio.to_thread(self.service.state)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("summary", "Unable to read THPM state")))
            self.plugins = list(payload.get("plugins", []))  # type: ignore[arg-type]
            self.counts = {key: int(value) for key, value in dict(payload.get("counts", {})).items()}
            self.menu_surface = str(payload.get("menuSurface", "gui"))
            self.render_counts()
            self.render_menu_surface()
            await self.render_plugins(self.query_one("#integration-search", Input).value)
            self.set_message(self.palette_warning or "")
        except Exception as exc:
            self.set_message(f"Unable to read THPM state: {exc}", error=True)

    def render_counts(self) -> None:
        self.query_one("#metric-active", Static).update(str(self.counts["enabled"]))
        attention = self.counts["attention"]
        self.query_one("#metric-health", Static).update(str(attention) if attention else "Ready")
        self.query_one("#metric-health-detail", Static).update(
            "integrations need attention" if attention else "no integration warnings"
        )
        self.query_one("#metric-native", Static).update(str(self.counts["native"]))
        self.query_one("#metric-unavailable", Static).update(str(self.counts["unavailable"]))
        self.query_one("#sidebar-health", Static).update(
            f"{attention} need attention" if attention else "All systems ready"
        )
        self.query_one("#integration-summary", Static).update(
            f"{self.counts['enabled']} enabled · {self.counts['native']} handled by Omarchy"
        )
        if self.section == "integrations":
            self.query_one("#section-subtitle", Static).update(
                f"{self.counts['enabled']} enabled · {self.counts['native']} handled by Omarchy"
            )

    async def render_plugins(self, query: str = "") -> None:
        needle = query.strip().lower()
        visible = [
            plugin for plugin in self.plugins
            if not needle or needle in " ".join(
                str(plugin.get(key, "")) for key in ("label", "id", "category", "description")
            ).lower()
        ]
        plugin_list = self.query_one("#plugin-list", ListView)
        await plugin_list.clear()
        if visible:
            await plugin_list.extend(PluginRow(plugin) for plugin in visible)
        self.query_one("#no-integrations", Static).display = not visible
        plugin_list.display = bool(visible)

    def plugin_confirmed(self, plugin_id: str, confirmed: bool) -> None:
        if confirmed:
            self.set_plugin(plugin_id, True, True)
        else:
            self.load_state()

    @work(exclusive=True, group="mutation", exit_on_error=False)
    async def set_plugin(self, plugin_id: str, enabled: bool, confirmed: bool = False) -> None:
        self.set_busy(True)
        try:
            payload = await asyncio.to_thread(self.service.set_enabled, plugin_id, enabled, confirmed=confirmed)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("summary", "Action failed")))
            self.notify(f"{plugin_id} {'enabled' if enabled else 'disabled'}.")
        except Exception as exc:
            self.notify(str(exc), severity="error")
        finally:
            self.set_busy(False)
            self.load_state()

    @work(exclusive=True, group="menu-surface", exit_on_error=False)
    async def set_menu_surface(self, surface: str) -> None:
        if surface == self.menu_surface:
            return
        self.set_busy(True)
        message = self.query_one("#menu-surface-message", Static)
        message.update(f"Switching Omarchy Menu to the {surface.upper()}…")
        try:
            payload = await asyncio.to_thread(self.service.ui_surface, surface)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("summary", "Unable to change menu launcher")))
            result = dict(payload.get("result", {}))
            self.menu_surface = str(result.get("surface", surface))
            self.render_menu_surface()
            message.update(f"Omarchy Menu now opens the {self.menu_surface.upper()}.")
        except Exception as exc:
            message.update(str(exc))
            self.notify(str(exc), severity="error")
        finally:
            self.set_busy(False)

    def render_menu_surface(self) -> None:
        gui = self.menu_surface == "gui"
        self.query_one("#menu-surface-detail", Static).update(
            "Omarchy Menu opens the graphical window" if gui else "Omarchy Menu opens the terminal interface"
        )
        self.query_one("#menu-surface-gui", Button).set_class(gui, "selected")
        self.query_one("#menu-surface-tui", Button).set_class(not gui, "selected")

    @work(exclusive=True, group="doctor", exit_on_error=False)
    async def run_doctor(self) -> None:
        self.doctor_has_run = True
        summary = self.query_one("#doctor-summary", Label)
        summary.update("Checking THPM…")
        self.query_one("#run-doctor", Button).disabled = True
        try:
            payload = await asyncio.to_thread(self.service.doctor)
            summary.update(str(payload.get("summary", "Doctor complete")))
            caps = dict(payload.get("capabilities", {}))
            self.query_one("#doctor-detail", Static).update(f"{len(caps.get('routes', []))} Omarchy routes available")
            items: list[tuple[str, str, str]] = []
            for severity in ("errors", "warnings"):
                for item in payload.get(severity, []):
                    entry = dict(item)
                    items.append(("error" if severity == "errors" else "warning", str(entry.get("plugin", "System")), str(entry.get("message", ""))))
            results = self.query_one("#doctor-results", VerticalScroll)
            await results.remove_children()
            if not items:
                await results.mount(Static("✓  No issues found", classes="healthy-result"))
            else:
                await results.mount(*(
                    Static(f"{'ERROR' if severity == 'error' else 'WARN '}  {plugin} · {message}", classes=f"doctor-item {severity}")
                    for severity, plugin, message in items
                ))
        except Exception as exc:
            summary.update("Doctor failed")
            self.notify(str(exc), severity="error")
        finally:
            self.query_one("#run-doctor", Button).disabled = False

    @work(exclusive=True, group="system", exit_on_error=False)
    async def run_system_action(self, operation: str) -> None:
        self.set_busy(True)
        labels = {"apply": "Applying active theme…", "reconcile": "Reconciling integrations…"}
        self.query_one("#system-message", Static).update(labels[operation])
        try:
            call = self.service.run_theme if operation == "apply" else lambda: self.service.reconcile(True)
            payload = await asyncio.to_thread(call)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("summary", "Action failed")))
            message = "Active theme reapplied." if operation == "apply" else "Templates reconciled and theme refreshed."
            self.query_one("#system-message", Static).update(message)
            self.notify(message)
            self.load_state()
        except Exception as exc:
            self.query_one("#system-message", Static).update(str(exc))
            self.notify(str(exc), severity="error")
        finally:
            self.set_busy(False)

    @work(exclusive=True, group="update-check", exit_on_error=False)
    async def check_update(self, force: bool) -> None:
        button = self.query_one("#update-action", Button)
        button.disabled = True
        button.label = "Checking…"
        try:
            payload = await asyncio.to_thread(self.service.update_check, force)
            result = dict(payload.get("result", {}))
            self.update_info = result
            self.render_update()
            if not payload.get("ok") and force:
                self.notify(str(payload.get("summary", "Update check failed")), severity="error")
        except Exception as exc:
            self.update_info = {"status": "error", "currentVersion": __version__, "availableVersion": None}
            self.render_update()
            if force:
                self.notify(str(exc), severity="error")
        finally:
            button.disabled = False

    def render_update(self) -> None:
        status = str(self.update_info.get("status", "idle"))
        current = str(self.update_info.get("currentVersion") or __version__)
        available = self.update_info.get("availableVersion")
        detail = f"Version {available} is available" if status == "available" else f"Installed version {current}"
        self.query_one("#update-detail", Static).update(detail)
        self.query_one("#update-action", Button).label = "Update" if status == "available" else "Check now"
        self.query_one("#header-update", Button).label = f"Update {available}" if status == "available" else "Updates"
        if status == "error":
            self.query_one("#update-message", Static).update("Update status unavailable")

    def confirm_update(self) -> None:
        current = str(self.update_info.get("currentVersion") or __version__)
        available = str(self.update_info.get("availableVersion") or "new version")
        self.push_screen(ConfirmUpdate(current, available), self.update_confirmed)

    def update_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self.apply_update()

    @work(exclusive=True, group="update-apply", exit_on_error=False)
    async def apply_update(self) -> None:
        self.set_busy(True)
        self.query_one("#update-message", Static).update("Downloading and verifying update…")
        try:
            payload = await asyncio.to_thread(self.service.update_apply)
            result = dict(payload.get("result", {}))
            self.update_info = result
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("summary", "Update not applied")))
            status = str(result.get("status", ""))
            if status == "updated":
                message = f"Updated to {result.get('availableVersion')}. Restart the shell and relaunch this TUI."
                self.query_one("#restart-shell", Button).display = True
            elif status == "started":
                message = "Package update opened in a terminal."
            else:
                message = "THPM is current."
            self.query_one("#update-message", Static).update(message)
            self.notify(message)
            self.render_update()
        except Exception as exc:
            self.query_one("#update-message", Static).update(str(exc))
            self.notify(str(exc), severity="error")
        finally:
            self.set_busy(False)

    @work(exclusive=True, group="restart", exit_on_error=False)
    async def restart_shell(self) -> None:
        self.set_busy(True)
        try:
            completed = await asyncio.to_thread(run, "restart", "shell", check=False)
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "Unable to restart Omarchy Shell")
            self.notify("Omarchy Shell restarted.")
        except Exception as exc:
            self.notify(str(exc), severity="error")
        finally:
            self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.set_class(busy, "busy")
        for selector in ("#overview-apply", "#system-apply", "#system-reconcile", "#menu-surface-gui", "#menu-surface-tui", "#update-action", "#header-update", "#restart-shell"):
            self.query_one(selector, Button).disabled = busy

    def set_message(self, message: str, error: bool = False) -> None:
        widget = self.query_one("#message", Static)
        widget.update(message)
        widget.set_class(error, "error")
        widget.display = bool(message)


def run_tui(service: Service | None = None, paths: Paths | None = None) -> None:
    ThpmTui(service=service, paths=paths).run()
