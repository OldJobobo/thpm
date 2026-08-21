:root {
    --thpm-bg: {{ background }};
    --thpm-surface: {{ lighter_background }};
    --thpm-surface-raised: {{ darker_background }};
    --thpm-fg: {{ foreground }};
    --thpm-muted: {{ muted }};
    --thpm-accent: {{ magenta }};

    --zen-colors-primary: var(--thpm-bg) !important;
    --zen-colors-secondary: var(--thpm-surface) !important;
    --zen-colors-tertiary: var(--thpm-surface-raised) !important;
    --zen-colors-border: var(--thpm-surface) !important;
    --zen-main-browser-background: var(--thpm-bg) !important;
    --lwt-accent-color: var(--thpm-bg) !important;
    --lwt-text-color: var(--thpm-fg) !important;
    --lwt-sidebar-background-color: var(--thpm-bg) !important;
    --lwt-sidebar-text-color: var(--thpm-fg) !important;
    --toolbar-bgcolor: var(--thpm-bg) !important;
    --toolbar-color: var(--thpm-fg) !important;
    --toolbar-field-background-color: var(--thpm-surface) !important;
    --toolbar-field-color: var(--thpm-fg) !important;
    --arrowpanel-background: var(--thpm-surface) !important;
    --arrowpanel-color: var(--thpm-fg) !important;
    --in-content-page-background: var(--thpm-bg) !important;
    --focus-outline-color: var(--thpm-accent) !important;
}

#main-window,
#navigator-toolbox,
#titlebar,
#TabsToolbar,
#nav-bar,
#PersonalToolbar,
#zen-sidebar-top-buttons,
#zen-sidebar-foot-buttons,
#zen-appcontent-wrapper {
    background-color: var(--thpm-bg) !important;
    color: var(--thpm-fg) !important;
    border-color: var(--thpm-surface) !important;
}

#urlbar-background,
#searchbar {
    background-color: var(--thpm-surface) !important;
    color: var(--thpm-fg) !important;
}

#zen-sidebar-top-buttons toolbarbutton,
#zen-sidebar-foot-buttons toolbarbutton,
#nav-bar toolbarbutton,
#TabsToolbar toolbarbutton {
    color: var(--thpm-fg) !important;
    fill: var(--thpm-muted) !important;
}
