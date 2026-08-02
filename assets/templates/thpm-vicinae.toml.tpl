[meta]
version = 1
name = "THPM Current"
description = "Follow the active Omarchy theme through THPM."
variant = "{{ mode }}"
inherits = "vicinae-{{ mode }}"

[colors.core]
background = "{{ background }}"
foreground = "{{ foreground }}"
secondary_background = "{{ dark_background }}"
border = "{{ muted }}"
accent = "{{ blue }}"

[colors.accents]
blue = "{{ blue }}"
green = "{{ green }}"
magenta = "{{ magenta }}"
orange = "{{ orange }}"
purple = "{{ magenta }}"
red = "{{ red }}"
yellow = "{{ yellow }}"
cyan = "{{ cyan }}"

[colors.text]
default = "{{ foreground }}"
muted = "{{ muted }}"
danger = "{{ red }}"
selection = { background = "{{ selection }}", foreground = "{{ foreground }}" }

[colors.list.item.hover]
background = "{{ lighter_background }}"
foreground = "{{ foreground }}"

[colors.list.item.selection]
background = "{{ selection }}"
foreground = "{{ foreground }}"
secondary_background = "{{ selection }}"
secondary_foreground = "{{ foreground }}"
