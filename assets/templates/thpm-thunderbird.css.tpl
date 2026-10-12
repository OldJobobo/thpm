/* THPM Thunderbird theming.
 *
 * This one generated stylesheet is imported into both userChrome.css and
 * userContent.css, because Thunderbird's outer window and its about:3pane /
 * about:message views are separate documents with separate cascades. Every
 * rule below is therefore scoped to the document type it is meant for, so
 * the file is inert in whichever entrypoint it does not apply to and never
 * leaks chrome declarations into mail content.
 *
 * The accent tokens below go through Omarchy's gradient_start resolver with
 * an explicit blue fallback rather than referencing the accent color
 * directly. Accent is an optional semantic color, a direct reference would
 * render literally on a palette that omits it, and THPM refuses to apply a
 * generated file that still contains an unresolved placeholder.
 */

@-moz-document url-prefix("chrome://") {
  :root {
    --layout-background-0: {{ background }} !important;
    --layout-background-1: {{ background }} !important;
    --layout-background-2: {{ dark_background }} !important;
    --layout-background-3: {{ lighter_background }} !important;
    --layout-background-4: {{ lighter_background }} !important;

    --layout-color-0: {{ bright_foreground }} !important;
    --layout-color-1: {{ foreground }} !important;
    --layout-color-2: {{ dark_foreground }} !important;
    --layout-color-3: {{ muted }} !important;

    --layout-border-0: {{ selection }} !important;
    --layout-border-1: {{ selection }} !important;
    --layout-border-2: {{ selection }} !important;

    --selected-item-color: {{ gradient_start accent blue }} !important;
    --selected-item-text-color: {{ darker_background }} !important;

    --color-surface-subtle: {{ lighter_background }} !important;
    --color-text-base: {{ foreground }} !important;
    --color-surface-border-intense: {{ selection }} !important;

    /* The variables below are the ones a lightweight theme add-on sets
     * through LightweightThemeConsumer. Most are consumed as plain var()
     * lookups rather than behind the :root[lwtheme] attribute that only
     * that consumer can set, so setting them here reaches the same
     * toolbars, panels, icons and sidebars the add-on would reach. */
    --toolbar-background-color: {{ background }} !important;
    --toolbar-text-color: {{ foreground }} !important;
    --toolbarbutton-icon-fill: {{ foreground }} !important;
    --toolbarbutton-icon-fill-attention: {{ gradient_start accent blue }} !important;
    --toolbarseparator-color: {{ selection }} !important;
    --chrome-content-separator-color: {{ selection }} !important;

    --toolbar-field-background-color: {{ lighter_background }} !important;
    --toolbar-field-text-color: {{ foreground }} !important;
    --toolbar-field-border-color: {{ selection }} !important;
    --toolbar-field-background-color-focus: {{ lighter_background }} !important;
    --toolbar-field-text-color-focus: {{ foreground }} !important;

    --panel-background-color: {{ lighter_background }} !important;
    --panel-text-color: {{ foreground }} !important;
    --panel-border-color: {{ selection }} !important;
    --autocomplete-popup-highlight-background: {{ gradient_start accent blue }} !important;
    --autocomplete-popup-highlight-color: {{ darker_background }} !important;

    --sidebar-background-color: {{ dark_background }} !important;
    --sidebar-text-color: {{ foreground }} !important;
    --sidebar-border-color: {{ selection }} !important;
    --sidebar-highlight-background-color: {{ gradient_start accent blue }} !important;
    --sidebar-highlight-text-color: {{ darker_background }} !important;
    --sidebar-highlight-border-color: {{ gradient_start accent blue }} !important;

    --lwt-tab-text: {{ foreground }} !important;
    --lwt-tab-line-color: {{ gradient_start accent blue }} !important;
    --lwt-background-tab-separator-color: {{ selection }} !important;
    --lwt-tabs-border-color: {{ selection }} !important;
    --tab-loading-fill: {{ gradient_start accent blue }} !important;

    --lwt-toolbarbutton-hover-background: {{ selection }} !important;
    --lwt-toolbarbutton-active-background: {{ gradient_start accent blue }} !important;
    --lwt-toolbarbutton-icon-fill-attention: {{ gradient_start accent blue }} !important;
  }

  /* #navigation-toolbox only reads --lwt-accent-color or
   * --toolbar-background-color under :root[lwtheme]; without that attribute
   * it falls back to the native -moz-headerbar/ActiveCaption system color
   * and ignores the variables above. It has to be set directly. */
  #navigation-toolbox {
    background-color: {{ background }} !important;
    color: {{ foreground }} !important;
  }
}

@-moz-document url("about:3pane"), url("about:message") {
  :root {
    --layout-background-0: {{ background }} !important;
    --layout-background-1: {{ background }} !important;
    --layout-background-2: {{ dark_background }} !important;
    --layout-background-3: {{ lighter_background }} !important;
    --layout-background-4: {{ lighter_background }} !important;

    --layout-color-0: {{ bright_foreground }} !important;
    --layout-color-1: {{ foreground }} !important;
    --layout-color-2: {{ dark_foreground }} !important;
    --layout-color-3: {{ muted }} !important;

    --layout-border-0: {{ selection }} !important;
    --layout-border-1: {{ selection }} !important;
    --layout-border-2: {{ selection }} !important;

    --selected-item-color: {{ gradient_start accent blue }} !important;
    --selected-item-text-color: {{ darker_background }} !important;

    --color-surface-subtle: {{ lighter_background }} !important;
    --color-text-base: {{ foreground }} !important;
    --color-surface-border-intense: {{ selection }} !important;

    --sidebar-highlight-background-color: {{ gradient_start accent blue }} !important;
    --sidebar-highlight-text-color: {{ darker_background }} !important;
    --toolbarbutton-icon-fill: {{ foreground }} !important;
    --toolbarbutton-icon-fill-attention: {{ gradient_start accent blue }} !important;
  }
}
