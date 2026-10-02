#!/usr/bin/env bash
# stress.sh — build mayc and run the full stress test through both compilers.
#
# The reference compiler and mayc must produce byte-identical output.  The
# script also reports wall-clock time and the peak resident set size of the
# mayc-compiled binary (which exercises the collector for many cycles).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
cd "$ROOT"

HOST="$ROOT/target/release/maylang"
MAYC="$ROOT/toolchain/mayc/mayc_stage0"
SRC="$HERE/stress.may"

if [ ! -x "$HOST" ]; then
    echo "building reference compiler..."
    cargo build --release || exit 1
fi

echo "building mayc (stage0) with the reference compiler..."
"$HOST" build -o "$MAYC" toolchain/mayc/main.may || exit 1

echo "compiling $SRC with mayc..."
"$MAYC" "$SRC" -o /tmp/mayc_stress_bin || exit 1

# Run a command, sampling its peak RSS (Linux /proc), writing stdout to $1.
run_timed() {
    local out="$1"; shift
    local start end
    start=$(date +%s%N)
    "$@" > "$out" 2>&1 &
    local pid=$!
    local peak=0
    while kill -0 "$pid" 2>/dev/null; do
        local rss
        rss=$(awk '/VmRSS/{print $2}' "/proc/$pid/status" 2>/dev/null)
        [ -n "${rss:-}" ] && [ "$rss" -gt "$peak" ] && peak=$rss
        sleep 0.05
    done
    wait "$pid"
    local rc=$?
    end=$(date +%s%N)
    local ms=$(( (end - start) / 1000000 ))
    printf '%s' "$rc $ms $peak"
}

echo "running reference compiler..."
read -r host_rc host_ms host_peak < <(run_timed /tmp/mayc_stress_host.out "$HOST" run "$SRC")
echo "running mayc-compiled stress binary..."
read -r mayc_rc mayc_ms mayc_peak < <(run_timed /tmp/mayc_stress_mayc.out /tmp/mayc_stress_bin)

echo
printf 'reference : exit=%s  time=%sms  peak=%s kB\n' "$host_rc" "$host_ms" "$host_peak"
printf 'mayc      : exit=%s  time=%sms  peak=%s kB\n' "$mayc_rc" "$mayc_ms" "$mayc_peak"
echo

if [ "$host_rc" -ne 0 ] || [ "$mayc_rc" -ne 0 ]; then
    echo "FAIL: non-zero exit"
    diff /tmp/mayc_stress_host.out /tmp/mayc_stress_mayc.out | head -20
    exit 1
fi

if diff -q /tmp/mayc_stress_host.out /tmp/mayc_stress_mayc.out >/dev/null 2>&1; then
    echo "PASS: stress output matches exactly ($(wc -l < /tmp/mayc_stress_host.out) lines)"
    exit 0
else
    echo "FAIL: output differs"
    diff /tmp/mayc_stress_host.out /tmp/mayc_stress_mayc.out | head -20
    exit 1
fi
