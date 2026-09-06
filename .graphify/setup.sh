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

echo "Graphify $EXPECTED_VERSION setup complete."
