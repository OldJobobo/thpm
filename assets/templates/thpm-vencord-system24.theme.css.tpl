/**
 * @name Omarchy System24
 * @description System24 using the active Omarchy semantic palette.
 * @author OldJobobo, refact0r
 * @version 1.0.0rc1
 * @website https://github.com/refact0r/system24
 * @source https://github.com/refact0r/system24
 */

@import url("https://refact0r.github.io/system24/build/system24.css");

body {
    --font: "DM Mono";
    --code-font: "DM Mono";
    --gap: 12px;
    --divider-thickness: 4px;
    --border-thickness: 2px;
    --animations: on;
    --top-bar-height: var(--gap);
    --top-bar-button-position: titlebar;
    --top-bar-title-position: off;
    --custom-window-controls: off;
    --custom-dms-icon: hide;
    --background-image: off;
    --transparency-tweaks: off;
    --small-user-panel: on;
    --unrounding: on;
    --custom-spotify-bar: on;
    --ascii-titles: on;
    --ascii-loader: system24;
    --panel-labels: on;
}

:root {
    --colors: on;

    --text-0: {{ bg }};
    --text-1: {{ bright_fg }};
    --text-2: {{ fg }};
    --text-3: {{ light_fg }};
    --text-4: {{ muted }};
    --text-5: {{ dark_fg }};

    --bg-1: color-mix(in srgb, {{ bg }}, {{ fg }} 18%);
    --bg-2: color-mix(in srgb, {{ bg }}, {{ fg }} 12%);
    --bg-3: color-mix(in srgb, {{ bg }}, {{ fg }} 6%);
    --bg-4: {{ bg }};
    --hover: color-mix(in srgb, {{ muted }} 18%, transparent);
    --active: color-mix(in srgb, {{ muted }} 28%, transparent);
    --active-2: color-mix(in srgb, {{ muted }} 38%, transparent);
    --message-hover: color-mix(in srgb, {{ darker_bg }} 55%, transparent);

    --accent-1: {{ bright_blue }};
    --accent-2: {{ blue }};
    --accent-3: {{ blue }};
    --accent-4: {{ bright_blue }};
    --accent-5: color-mix(in srgb, {{ blue }}, {{ bg }} 28%);
    --accent-new: var(--red-2);

    --online: {{ green }};
    --dnd: {{ red }};
    --idle: {{ yellow }};
    --streaming: {{ magenta }};
    --offline: {{ muted }};

    --text-normal: var(--text-2);
    --text-muted: var(--text-5);
    --header-primary: var(--text-1);
    --header-secondary: var(--text-3);
    --interactive-normal: var(--text-4);
    --interactive-hover: var(--text-2);
    --interactive-active: var(--text-1);
    --interactive-muted: var(--text-5);
    --channels-default: var(--text-5);
    --channel-icon: var(--text-5);
    --background-primary: var(--bg-4);
    --background-secondary: var(--bg-3);
    --background-secondary-alt: var(--bg-2);
    --background-tertiary: var(--bg-1);

    --red-1: {{ bright_red }};
    --red-2: {{ red }};
    --red-3: {{ red }};
    --red-4: color-mix(in srgb, {{ red }}, {{ bg }} 18%);
    --red-5: color-mix(in srgb, {{ red }}, {{ bg }} 34%);
    --green-1: {{ bright_green }};
    --green-2: {{ green }};
    --green-3: {{ green }};
    --green-4: color-mix(in srgb, {{ green }}, {{ bg }} 18%);
    --green-5: color-mix(in srgb, {{ green }}, {{ bg }} 34%);
    --blue-1: {{ bright_blue }};
    --blue-2: {{ blue }};
    --blue-3: {{ blue }};
    --blue-4: color-mix(in srgb, {{ blue }}, {{ bg }} 18%);
    --blue-5: color-mix(in srgb, {{ blue }}, {{ bg }} 34%);
    --yellow-1: {{ bright_yellow }};
    --yellow-2: {{ yellow }};
    --yellow-3: {{ yellow }};
    --yellow-4: color-mix(in srgb, {{ yellow }}, {{ bg }} 18%);
    --yellow-5: color-mix(in srgb, {{ yellow }}, {{ bg }} 34%);
    --purple-1: {{ bright_magenta }};
    --purple-2: {{ magenta }};
    --purple-3: {{ magenta }};
    --purple-4: color-mix(in srgb, {{ magenta }}, {{ bg }} 18%);
    --purple-5: color-mix(in srgb, {{ magenta }}, {{ bg }} 34%);
}

:is([class*="containerDefault_"], [class*="containerDragAfter_"], [class*="containerDragBefore_"])
    [class*="wrapper_"]:not([class*="modeUnread"]):not([class*="modeSelected"]):not([class*="modeConnected"]):not(:hover)
    :is([class*="name_"], [class*="icon_"]) {
    color: var(--text-5) !important;
}
