/**
 * @name Omarchy Midnight
 * @description Midnight-based Discord surface using the active Omarchy semantic palette.
 * @author OldJobobo, refact0r
 * @version 1.0.0
 * @website https://github.com/OldJobobo/thpm
 * @source https://github.com/OldJobobo/thpm
 * @upstream https://github.com/refact0r/midnight-discord
 */

@import url("https://cdn.jsdelivr.net/gh/OldJobobo/thpm@main/assets/vencord/thpm-midnight.css");

body {
    --font: "Figtree";
    --code-font: "Figtree";
    font-weight: 400;

    --gap: 12px;
    --divider-thickness: 4px;
    --border-thickness: 1px;

    --animations: on;
    --top-bar-height: var(--gap);
    --top-bar-button-position: titlebar;
    --top-bar-title-position: off;
    --subtle-top-bar-title: off;
    --custom-window-controls: off;
    --custom-dms-icon: off;
    --custom-dms-background: off;
    --background-image: off;
    --transparency-tweaks: off;
    --remove-bg-layer: off;
    --panel-blur: off;
    --custom-chatbar: off;
    --small-user-panel: on;
}

:root {
    --colors: on;

    /* Colored control surfaces below are lifted enough for stable black text. */
    --text-0: #000000;
    --text-1: {{ bright_foreground }};
    --text-2: {{ foreground }};
    --text-3: {{ light_foreground }};
    --text-4: {{ muted }};
    --text-5: {{ dark_foreground }};

    --bg-1: color-mix(in srgb, {{ background }}, {{ foreground }} 18%);
    --bg-2: color-mix(in srgb, {{ background }}, {{ foreground }} 12%);
    --bg-3: color-mix(in srgb, {{ background }}, {{ foreground }} 6%);
    --bg-4: {{ background }};
    --hover: color-mix(in srgb, {{ muted }} 18%, transparent);
    --active: color-mix(in srgb, {{ muted }} 28%, transparent);
    --active-2: color-mix(in srgb, {{ muted }} 38%, transparent);
    --message-hover: color-mix(in srgb, {{ darker_background }} 55%, transparent);

    --accent-1: {{ bright_blue }};
    --accent-2: color-mix(in srgb, {{ blue }}, #ffffff 40%);
    --accent-3: color-mix(in srgb, {{ blue }}, #ffffff 40%);
    --accent-4: color-mix(in srgb, {{ blue }}, #ffffff 48%);
    --accent-5: color-mix(in srgb, {{ blue }}, #ffffff 56%);
    --accent-new: var(--red-2);

    --online: {{ green }};
    --dnd: {{ red }};
    --idle: {{ yellow }};
    --streaming: {{ magenta }};
    --offline: {{ muted }};

    --border-light: var(--hover);
    --border: var(--active);
    --border-hover: var(--active-2);
    --button-border: color-mix(in srgb, {{ foreground }} 12%, transparent);

    --red-1: {{ bright_red }};
    --red-2: color-mix(in srgb, {{ red }}, #ffffff 40%);
    --red-3: color-mix(in srgb, {{ red }}, #ffffff 40%);
    --red-4: color-mix(in srgb, {{ red }}, #ffffff 48%);
    --red-5: color-mix(in srgb, {{ red }}, #ffffff 56%);
    --green-1: {{ bright_green }};
    --green-2: color-mix(in srgb, {{ green }}, #ffffff 40%);
    --green-3: color-mix(in srgb, {{ green }}, #ffffff 40%);
    --green-4: color-mix(in srgb, {{ green }}, #ffffff 48%);
    --green-5: color-mix(in srgb, {{ green }}, #ffffff 56%);
    --blue-1: {{ bright_blue }};
    --blue-2: color-mix(in srgb, {{ blue }}, #ffffff 40%);
    --blue-3: color-mix(in srgb, {{ blue }}, #ffffff 40%);
    --blue-4: color-mix(in srgb, {{ blue }}, #ffffff 48%);
    --blue-5: color-mix(in srgb, {{ blue }}, #ffffff 56%);
    --yellow-1: {{ bright_yellow }};
    --yellow-2: color-mix(in srgb, {{ yellow }}, #ffffff 40%);
    --yellow-3: color-mix(in srgb, {{ yellow }}, #ffffff 40%);
    --yellow-4: color-mix(in srgb, {{ yellow }}, #ffffff 48%);
    --yellow-5: color-mix(in srgb, {{ yellow }}, #ffffff 56%);
    --purple-1: {{ bright_magenta }};
    --purple-2: color-mix(in srgb, {{ magenta }}, #ffffff 40%);
    --purple-3: color-mix(in srgb, {{ magenta }}, #ffffff 40%);
    --purple-4: color-mix(in srgb, {{ magenta }}, #ffffff 48%);
    --purple-5: color-mix(in srgb, {{ magenta }}, #ffffff 56%);
}
