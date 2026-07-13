#!/usr/bin/env bash
# Transitional helpers for independently authored hooks that used THPM's old helper path.
skipped() {
    printf 'Skipped: %s\n' "${1:-optional integration unavailable}"
    exit 0
}

success() {
    printf '%s\n' "${1:-Theme integration updated}"
}

warning() {
    printf 'Warning: %s\n' "${1:-Theme integration needs attention}" >&2
}
