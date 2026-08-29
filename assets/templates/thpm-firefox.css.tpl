/* THPM Firefox theming.
 *
 * Imported into the profile's userChrome.css, which applies to chrome
 * documents only, so no document scoping is needed here.
 *
 * The variables below are the ones a lightweight theme add-on sets through
 * LightweightThemeConsumer. Most are consumed as plain var() lookups rather
 * than behind the :root[lwtheme] attribute that only that consumer can set,
 * so setting them from a plain stylesheet reaches the same toolbars, panels,
 * urlbar, sidebar, tabs and icons an add-on would reach. Verified against
 * Firefox 154's own chrome CSS; --lwt-accent-color, --lwt-text-color and
 * --lwt-tab-line-color are consumed only under that attribute and are
 * deliberately left unset, because setting them would have no effect.
 *
 * The accent token goes through Omarchy's gradient_start resolver with an
 * explicit blue fallback. Accent is an optional semantic color, a direct
 * reference would render literally on a palette that omits it, and THPM
 * refuses to apply a generated file with an unresolved placeholder.
 */

:root {
  --thpm-bg: {{ background }};
  --thpm-surface: {{ lighter_background }};
  --thpm-surface-raised: {{ dark_background }};
  --thpm-fg: {{ foreground }};
  --thpm-muted: {{ muted }};
  --thpm-border: {{ selection }};
  --thpm-accent: {{ gradient_start accent blue }};
  --thpm-on-accent: {{ darker_background }};

  --toolbar-background-color: var(--thpm-bg) !important;
  --toolbar-text-color: var(--thpm-fg) !important;
  --toolbarseparator-color: var(--thpm-border) !important;
  --chrome-content-separator-color: var(--thpm-border) !important;

  --toolbarbutton-icon-fill: var(--thpm-fg) !important;
  --toolbarbutton-icon-fill-attention: var(--thpm-accent) !important;
  --toolbarbutton-background-color-hover: var(--thpm-border) !important;
  --toolbarbutton-background-color-active: var(--thpm-accent) !important;

  --toolbar-field-background-color: var(--thpm-surface) !important;
  --toolbar-field-text-color: var(--thpm-fg) !important;
  --toolbar-field-border-color: var(--thpm-border) !important;
  --toolbar-field-background-color-focus: var(--thpm-surface) !important;
  --toolbar-field-text-color-focus: var(--thpm-fg) !important;

  --panel-background-color: var(--thpm-surface) !important;
  --panel-text-color: var(--thpm-fg) !important;
  --panel-border-color: var(--thpm-border) !important;

  --urlbarview-background-color-selected: var(--thpm-accent) !important;
  --urlbarview-text-color-selected: var(--thpm-on-accent) !important;

  --sidebar-background-color: var(--thpm-surface-raised) !important;
  --sidebar-text-color: var(--thpm-fg) !important;
  --sidebar-border-color: var(--thpm-border) !important;

  --tab-background-color-selected: var(--thpm-bg) !important;
  --tab-selected-textcolor: var(--thpm-fg) !important;

  --focus-outline-color: var(--thpm-accent) !important;
}

/* #navigator-toolbox only reads --lwt-accent-color under :root[lwtheme];
   without that attribute it falls back to the native system color and
   ignores the variables above, so it is set directly. */
#navigator-toolbox {
  background-color: var(--thpm-bg) !important;
  color: var(--thpm-fg) !important;
}
