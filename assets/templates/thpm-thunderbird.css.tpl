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
  }
}
