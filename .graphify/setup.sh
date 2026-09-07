#!/usr/bin/env bash
set -euo pipefail

EXPECTED_VERSION="0.9.51"
VERIFY_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --verify-only) VERIFY_ONLY=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is not installed or not in PATH." >&2
    exit 1
fi

INSTALLED_VERSION="$(graphify --version 2>/dev/null || true)"
if [ "$INSTALLED_VERSION" != "graphify $EXPECTED_VERSION" ]; then
    if [ "$VERIFY_ONLY" -eq 1 ]; then
        echo "Error: Expected graphify $EXPECTED_VERSION, but found '$INSTALLED_VERSION'." >&2
        exit 1
    fi
    echo "Installing graphifyy==$EXPECTED_VERSION via uv tool..."
    uv tool install --force "graphifyy==$EXPECTED_VERSION"
fi

if [ "$VERIFY_ONLY" -eq 1 ]; then
    echo "Graphify project configuration verified for $EXPECTED_VERSION."
    exit 0
fi

echo "Installing project-scoped skills and hooks..."
graphify install --project
graphify install --project --platform agents
graphify claude install --project
graphify codex install --project
graphify hook install

# `graphify hook install` writes a post-commit hook that rebuilds the graph
# after EVERY commit, which defeats AGENTS.md 7.2 (a single update once the
# work is stable) and pairs every code commit with a graph-sync commit.
# Re-apply the pause guard it overwrites. See AGENTS.md 7.3.
apply_pause_guard() {
    hook="$(git rev-parse --git-common-dir)/hooks/post-commit"
    [ -f "$hook" ] || { echo "No post-commit hook to guard; skipping." >&2; return 0; }
    if grep -q 'graphify-pause' "$hook"; then
        echo "Pause guard already present in post-commit hook."
        return 0
    fi
    anchor='[ "${GRAPHIFY_SKIP_HOOK:-0}" = "1" ] && exit 0'
    grep -qF "$anchor" "$hook" || {
        echo "Warning: post-commit hook lacks the expected GRAPHIFY_SKIP_HOOK anchor; pause guard NOT applied." >&2
        return 0
    }
    guard_tmp="$(mktemp)"
    cat > "$guard_tmp" <<'GUARD'
_GFY_PAUSE="$(git rev-parse --git-common-dir 2>/dev/null)/graphify-pause"
if [ -f "$_GFY_PAUSE" ]; then
    echo "[graphify hook] paused ($_GFY_PAUSE); run 'graphify update .' when the work is stable" >&2
    exit 0
fi
GUARD
    awk -v guard_file="$guard_tmp" -v anchor="$anchor" '
        { print }
        $0 == anchor && !done {
            print ""
            while ((getline line < guard_file) > 0) print line
            done = 1
        }
    ' "$hook" > "$hook.new"
    rm -f "$guard_tmp"
    chmod +x "$hook.new"
    mv "$hook.new" "$hook"
    echo "Pause guard applied to post-commit hook (AGENTS.md 7.3)."
}
apply_pause_guard

echo "Graphify $EXPECTED_VERSION setup complete."
