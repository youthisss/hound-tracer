#!/usr/bin/env sh
set -eu

PACKAGE="hound-tracer"
VERSION="${HOUND_VERSION:-}"

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

case "$(uname -s 2>/dev/null || true)" in
    Linux|Darwin) ;;
    *) fail "this installer supports Linux, macOS, and WSL; use install.ps1 on native Windows" ;;
esac

if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
else
    command -v curl >/dev/null 2>&1 || fail "curl is required to install uv"
    say "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    UV=""
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            UV="$candidate"
            break
        fi
    done
    [ -n "$UV" ] || fail "uv was installed but could not be found; open a new shell and run this installer again"
fi

if [ -n "$VERSION" ]; then
    SPEC="${PACKAGE}==${VERSION}"
else
    SPEC="$PACKAGE"
fi

say "Installing ${SPEC}..."
"$UV" tool install --force "$SPEC"

BIN_DIR="$($UV tool dir --bin)"
HOUND="$BIN_DIR/hound"
[ -x "$HOUND" ] || fail "installation completed but $HOUND was not created"

say ""
"$HOUND" --version
say "Installed successfully."
case ":${PATH:-}:" in
    *":$BIN_DIR:"*) say "Run: hound doctor" ;;
    *) say "Open a new shell, then run: hound doctor" ;;
esac
