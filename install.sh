#!/bin/sh
# Download the native Maylang installer. Safe to feed to a POSIX shell on stdin.
# Keep execution inside main so a truncated download cannot run a partial script.
set -eu

main() {
    for argument in "$@"; do
        case "$argument" in
            --help|-h)
                cat <<'HELP'
Maylang — one command, your whole toolkit

Usage: install.sh [OPTIONS]
  -y, --yes             Install with the recommended settings, without prompts
      --prefix DIR      Install into DIR (default: ~/.maylang)
      --components LIST all, compiler, or comma-separated tool names
      --no-modify-path  Leave shell profiles untouched
      --profile FILE    Choose a shell profile
      --plain           Numbered menus and a scrolling transcript
      --no-color        Disable colors

The installer opens your terminal even when this script is piped into sh.
Set MAYLANG_VERSION=vX.Y.Z to choose a release. Linux x86-64 / WSL 2 required.
HELP
                return 0 ;;
        esac
    done
    case "$(uname -s):$(uname -m)" in
        Linux:x86_64) ;;
        *) printf '%s\n' 'Maylang currently installs on Linux x86-64 and x86-64 WSL 2.' >&2; return 1 ;;
    esac
    for command in curl mktemp chmod rm; do
        command -v "$command" >/dev/null 2>&1 || { printf 'Maylang needs %s. Install it and run this command again.\n' "$command" >&2; return 1; }
    done
    if command -v sha256sum >/dev/null 2>&1; then
        maylang_hash=sha256sum
    elif command -v shasum >/dev/null 2>&1; then
        maylang_hash=shasum
    else
        printf '%s\n' 'Maylang needs sha256sum (coreutils) or shasum to verify the download.' >&2; return 1
    fi
    maylang_root=${MAYLANG_DIST_ROOT:-https://github.com/mirged/maylang/releases}
    maylang_protocol='=https'
    case "$maylang_root" in
        https://*) ;;
        http://127.0.0.1:*|http://localhost:*) maylang_protocol='=http,https' ;;
        *) printf '%s\n' 'MAYLANG_DIST_ROOT must use HTTPS (loopback HTTP is supported for local tests).' >&2; return 1 ;;
    esac
    if [ -n "${MAYLANG_VERSION:-}" ]; then
        case "$MAYLANG_VERSION" in
            *[!A-Za-z0-9.-]*|.*|-*) printf '%s\n' 'Invalid MAYLANG_VERSION; use a release tag such as v0.12.0.' >&2; return 1 ;;
        esac
        maylang_url="$maylang_root/download/$MAYLANG_VERSION"
    else
        maylang_url="$maylang_root/latest/download"
    fi
    maylang_asset=maylang-init-x86_64-linux
    maylang_work=$(mktemp -d "${TMPDIR:-/tmp}/maylang-download-XXXXXX")
    trap 'rm -rf "$maylang_work"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' HUP TERM
    printf '\n  ↓ Downloading Maylang…\n' >&2
    maylang_progress=--silent
    if [ -t 2 ] && [ "${TERM:-dumb}" != dumb ]; then maylang_progress=--progress-bar; fi
    if ! curl --proto "$maylang_protocol" --proto-redir "$maylang_protocol" --tlsv1.2 \
        --fail --location --show-error "$maylang_progress" --retry 2 --connect-timeout 15 \
        "$maylang_url/$maylang_asset" -o "$maylang_work/$maylang_asset"; then
        printf '%s\n' 'Maylang could not download its installer. Check your connection and try again.' >&2; return 1
    fi
    if ! curl --proto "$maylang_protocol" --proto-redir "$maylang_protocol" --tlsv1.2 \
        --fail --location --silent --show-error --retry 2 --connect-timeout 15 \
        "$maylang_url/$maylang_asset.sha256" -o "$maylang_work/checksum"; then
        printf '%s\n' 'Maylang could not download the installer checksum. Please try again.' >&2; return 1
    fi
    IFS=' ' read -r maylang_expected maylang_checksum_name < "$maylang_work/checksum"
    case "$maylang_expected" in *[!0-9a-fA-F]*|'') printf '%s\n' 'Invalid installer checksum.' >&2; return 1 ;; esac
    [ "${#maylang_expected}" -eq 64 ] || { printf '%s\n' 'Invalid installer checksum.' >&2; return 1; }
    if [ "$maylang_hash" = sha256sum ]; then
        maylang_actual=$(sha256sum < "$maylang_work/$maylang_asset")
    else
        maylang_actual=$(shasum -a 256 < "$maylang_work/$maylang_asset")
    fi
    maylang_actual=${maylang_actual%% *}
    [ "$maylang_actual" = "$maylang_expected" ] || { printf '%s\n' 'The download did not match its checksum. Run the command again to fetch a fresh copy.' >&2; return 1; }
    chmod 700 "$maylang_work/$maylang_asset"
    printf '  ✓ Download verified\n' >&2
    maylang_status=0
    "$maylang_work/$maylang_asset" "$@" || maylang_status=$?
    return "$maylang_status"
}

main "$@"
