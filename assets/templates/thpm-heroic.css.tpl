body.thpm {
  /* Text colours */
  --text-default: {{ foreground }};
  --text-secondary: {{ dark_foreground }};
  --text-tertiary: {{ muted }};
  --text-quartenary: {{ muted }};
  --text-hover: {{ light_foreground }};
  --text-title: {{ bright_foreground }};
  --text-gametitle: var(--text-default);
  --text-danger: {{ red }};
  --text-warning: {{ yellow }};
  --text-log: {{ yellow }};
  --text-pause-cancel: {{ cyan }};

  /* Backgrounds, inputs, modals, search bar */
  --background: {{ background }};
  --background-darker: {{ dark_background }};
  --background-lighter: {{ lighter_background }};
  --background-secondary: {{ darker_background }};
  --body-background: {{ dark_background }};
  --current-background: var(--body-background);
  --navbar-background: {{ darker_background }};
  --navbar-active-background: {{ dark_background }};
  --input-background: {{ darker_background }};
  --modal-background: var(--background-darker);
  --modal-backdrop: var(--background-darker);
  --modal-border: var(--background);
  --search-bar-background: var(--background);
  --search-bar-border: var(--background-lighter);
  --controller-hints-background: transparent;
  --osk-background: var(--body-background);
  --osk-button-background: var(--input-background);
  --osk-button-border: var(--navbar-background);
  --icons-background: var(--background-darker);

  /* Accent and buttons */
  --accent: {{ blue }};
  --accent-overlay: {{ bright_blue }};
  --primary: {{ blue }};
  --primary-hover: {{ bright_blue }};
  --primary-button: var(--accent);
  --secondary-button: {{ cyan }};
  --button-stroke: var(--accent);
  --link-highlight: var(--accent);
  --play-button: {{ green }};
  --install-button: var(--primary);
  --download-button: var(--primary);
  --download-button-overlay: var(--primary-hover);
  --success-button: {{ green }};
  --cancel-button: {{ yellow }};
  --cancel-button-overlay: {{ bright_yellow }};
  --tertiary-button: {{ yellow }};
  --tertiary-button-overlay: {{ bright_yellow }};
  --success: {{ green }};
  --success-hover: {{ bright_green }};
  --danger: {{ red }};
  --danger-hover: {{ bright_red }};

  /* Sidebar and navigation */
  --navbar-active: var(--text-secondary);
  --navbar-inactive: {{ muted }};
  --navbar-accent: var(--accent);
  --divider: {{ muted }};

  /* Icons */
  --action-icon: var(--text-secondary);
  --action-icon-hover: var(--text-hover);
  --action-icon-active: var(--text-default);
  --icon-disabled: {{ muted }};
  --icon-disabled-overlay: var(--background-lighter);
  --disabled-button: var(--background-lighter);
  --disabled-button-overlay: {{ muted }};
  --alphabet-filter-accent-color: var(--accent);
  --alphabet-filter-accent-hover: var(--accent-overlay);

  /* Anticheat statuses */
  --anticheat-denied: {{ brown }};
  --anticheat-broken: {{ orange }};
  --anticheat-running: {{ cyan }};
  --anticheat-supported: {{ green }};
  --anticheat-planned: {{ magenta }};
  --anticheat-unknown: {{ muted }};

  /* Body gradient used by the game library */
  --gradient-body-background: linear-gradient(
    90deg,
    var(--background-darker) -32px,
    var(--body-background) 64px,
    var(--body-background) 100%
  );
}

body {
  background: var(--body-background);
  color: var(--text-default);
}
