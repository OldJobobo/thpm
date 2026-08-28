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

  --selected-item-color: {{ blue }} !important;
  --selected-item-text-color: {{ darker_background }} !important;

  --color-surface-subtle: {{ lighter_background }} !important;
  --color-text-base: {{ foreground }} !important;
  --color-surface-border-intense: {{ selection }} !important;

  /* Unlike most --lwt-* variables (gated behind the lwtheme JS-set root
     attribute, unreachable from CSS alone), these three are consumed as
     plain var() fallbacks in shared/variables.css, so they color toolbar
     button hover/active states and icon-fill-attention unconditionally. */
  --lwt-toolbarbutton-hover-background: {{ selection }} !important;
  --lwt-toolbarbutton-active-background: {{ blue }} !important;
  --lwt-toolbarbutton-icon-fill-attention: {{ blue }} !important;
}

/* #navigation-toolbox (the outer chrome window's menu bar / unified
   toolbar / tab strip container) only reads --lwt-accent-color or
   --toolbar-background-color under :root[lwtheme]; otherwise it falls
   back straight to the native -moz-headerbar/ActiveCaption system color
   and ignores every --layout-*/--toolbar-background-color variable
   above entirely. It has to be overridden directly, unconditionally.
   Toolbar buttons themselves are transparent in their idle state (also
   unconditional, see widgets.css), so this is what actually colors them. */
#navigation-toolbox {
  background-color: {{ background }} !important;
  color: {{ foreground }} !important;
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

    --selected-item-color: {{ blue }} !important;
    --selected-item-text-color: {{ darker_background }} !important;

    --color-surface-subtle: {{ lighter_background }} !important;
    --color-text-base: {{ foreground }} !important;
    --color-surface-border-intense: {{ selection }} !important;

    --lwt-toolbarbutton-hover-background: {{ selection }} !important;
    --lwt-toolbarbutton-active-background: {{ blue }} !important;
    --lwt-toolbarbutton-icon-fill-attention: {{ blue }} !important;
  }
}
