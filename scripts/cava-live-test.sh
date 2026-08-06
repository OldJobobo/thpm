#!/usr/bin/env bash
set -euo pipefail

for command in cava mkfifo; do
    command -v "$command" >/dev/null || {
        printf '%s is required\n' "$command" >&2
        exit 1
    }
done

sandbox="$(mktemp -d --tmpdir thpm-cava-live.XXXXXX)"
cava_pid=""
writer_pid=""
cleanup() {
    if [[ -n "$cava_pid" ]]; then
        kill "$cava_pid" 2>/dev/null || true
        sleep 0.1
        kill -KILL "$cava_pid" 2>/dev/null || true
        wait "$cava_pid" 2>/dev/null || true
    fi
    if [[ -n "$writer_pid" ]]; then
        kill "$writer_pid" 2>/dev/null || true
        wait "$writer_pid" 2>/dev/null || true
    fi
    rm -rf -- "$sandbox"
}
trap cleanup EXIT INT TERM

export HOME="$sandbox/home"
export XDG_CONFIG_HOME="$sandbox/config"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/cava/themes"
mkfifo "$sandbox/audio.fifo"

cat >"$sandbox/cava.ini" <<EOF
[general]
framerate = 10
bars = 2

[input]
method = fifo
source = $sandbox/audio.fifo
sample_rate = 44100
sample_bits = 16
channels = 2

[output]
method = raw
raw_target = $sandbox/cava.raw
data_format = ascii
ascii_max_range = 100

[color]
theme = 'thpm'
EOF

cat >"$XDG_CONFIG_HOME/cava/themes/thpm" <<'EOF'
[color]
gradient = 1
gradient_color_1 = '#112233'
gradient_color_2 = '#445566'
EOF

# Feed silence so the real application can initialize without using the desktop's
# audio session. This is an integration launch, not a side-effect-free config check.
dd if=/dev/zero of="$sandbox/audio.fifo" bs=4096 status=none &
writer_pid=$!
cava -p "$sandbox/cava.ini" >"$sandbox/stdout.log" 2>"$sandbox/stderr.log" &
cava_pid=$!
sleep 1
kill -0 "$cava_pid" 2>/dev/null || {
    cat "$sandbox/stderr.log" >&2
    printf 'Cava did not remain running with the isolated THPM theme\n' >&2
    exit 1
}

cat >"$XDG_CONFIG_HOME/cava/themes/thpm" <<'EOF'
[color]
gradient = 1
gradient_color_1 = '#aabbcc'
gradient_color_2 = '#ddeeff'
EOF
kill -USR1 "$cava_pid"
sleep 1
kill -0 "$cava_pid" 2>/dev/null || {
    cat "$sandbox/stderr.log" >&2
    printf 'Cava exited after SIGUSR1 reload\n' >&2
    exit 1
}

printf 'PASS: real Cava accepted the isolated thpm selector/theme and survived SIGUSR1 reload.\n'
printf 'This harness does not claim visual color verification or dry-run validation.\n'
