#!/bin/sh
# Exercise only the read-only gate, with local stand-ins for every external command.
set -eu
ROOT=$(git rev-parse --show-toplevel)
# Normalize drive-letter paths before putting a directory in the colon-separated PATH.
ROOT=$(CDPATH='' cd -- "$ROOT" && pwd)
GATE="$ROOT/scripts/release/verify_release.sh"
mkdir -p "$ROOT/.codex-tmp"
SCRATCH=$(mktemp -d "$ROOT/.codex-tmp/release-gate.XXXXXX")
mkdir -p "$SCRATCH/bin" "$SCRATCH/repo/web/node_modules/@playwright/test"
: > "$SCRATCH/repo/web/node_modules/@playwright/test/cli.js"

cat > "$SCRATCH/bin/git" <<'EOF'
#!/bin/sh
[ "$*" = 'rev-parse --show-toplevel' ] || exit 97
printf '%s\n' "$GATE_ROOT"
EOF
cat > "$SCRATCH/bin/python" <<'EOF'
#!/bin/sh
[ "${1:-}" != '-c' ] || exit 0
printf '%s\n' http >> "$GATE_TRACE"
exit "$GATE_HTTP_EXIT"
EOF
cat > "$SCRATCH/bin/node" <<'EOF'
#!/bin/sh
case "${1:-}" in
  -e) exit 0;;
  */cli.js)
    case "${2:-}" in
      --version) exit 0;;
      test)
        [ "$PWD" = "$GATE_ROOT/web" ] || exit 98
        [ "${LIVE_BASE_URL:-}" = 'https://squadopt.mymandev.com' ] || exit 98
        printf '%s\n' browser >> "$GATE_TRACE"
        exit "$GATE_BROWSER_EXIT";;
    esac;;
esac
exit 98
EOF
cat > "$SCRATCH/bin/sleep" <<'EOF'
#!/bin/sh
[ "$*" = 60 ] || exit 98
printf '%s\n' retry >> "$GATE_TRACE"
EOF
chmod +x "$SCRATCH/bin/git" "$SCRATCH/bin/python" "$SCRATCH/bin/node" "$SCRATCH/bin/sleep"

run_case() {
  label="$1"; http_exit="$2"; browser_exit="$3"; expected_exit="$4"; expected_trace="$5"
  trace="$SCRATCH/$label.trace"
  : > "$trace"
  if env PATH="$SCRATCH/bin:$PATH" CI= GATE_ROOT="$SCRATCH/repo" GATE_TRACE="$trace" \
    GATE_HTTP_EXIT="$http_exit" GATE_BROWSER_EXIT="$browser_exit" \
    sh "$GATE" 2026-11-26T12:00:00Z > "$SCRATCH/$label.log" 2>&1; then
    actual_exit=0
  else
    actual_exit=$?
  fi
  [ "$actual_exit" -eq "$expected_exit" ] || {
    echo "$label: exit $actual_exit, wanted $expected_exit" >&2; exit 1
  }
  [ "$(cat "$trace")" = "$expected_trace" ] || {
    echo "$label: gate steps ran in the wrong order" >&2; exit 1
  }
  echo "$label: passed"
}

run_case success 0 0 0 'http
browser'
run_case browser-failure 0 7 1 'http
browser'
run_case http-failure 3 0 1 'http
retry
http'
echo '3 local gate simulations passed; no deployment or network command ran'
