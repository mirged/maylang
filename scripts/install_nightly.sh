#!/bin/sh
# Build Maylang from this checkout and install it as a nightly into a managed
# prefix (default ~/.maylang), using the same installer as `make install`.
#
#   sh scripts/install_nightly.sh [--pull] [--prefix DIR] [--keep N]
#
#   --pull        fast-forward the current branch before building
#   --prefix DIR  install there instead of ~/.maylang (or $MAYLANG_PREFIX)
#   --keep N      afterwards, delete all but the newest N nightly releases
#                 (the selected one is always kept); default keeps everything
#
# The version is `<release>-nightly.<UTC date>.<commit>`, with `.dirty` when
# the working tree has uncommitted changes, so `ls <prefix>/releases` shows
# what each generation was built from. Shell profiles are left untouched;
# source <prefix>/env.sh as the installer documents.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
prefix=${MAYLANG_PREFIX:-$HOME/.maylang}
pull=0
keep=0
while [ "$#" -gt 0 ]; do
    case $1 in
        --pull) pull=1 ;;
        --prefix) shift; prefix=$1 ;;
        --prefix=*) prefix=${1#--prefix=} ;;
        --keep) shift; keep=$1 ;;
        --keep=*) keep=${1#--keep=} ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "install_nightly: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
case $keep in ''|*[!0-9]*) echo "install_nightly: --keep needs a number" >&2; exit 2 ;; esac

cd "$root"
if [ "$pull" = 1 ]; then git pull --ff-only; fi

echo "==> Building the compiler from source"
sh compiler/rust/build.sh
echo "==> Building the tools"
python3 scripts/build_tools.py --compiler compiler/mayc/mayc_new

release=$(cat build/dev/VERSION)
commit=$(git rev-parse --short=10 HEAD)
dirty=
if ! git diff --quiet HEAD -- 2>/dev/null; then dirty=.dirty; fi
version="$release-nightly.$(date -u +%Y%m%d).$commit$dirty"
printf '%s\n' "$version" > build/dev/VERSION

echo "==> Checking the new compiler before installing it"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
build/dev/bin/mayc examples/hello.may -o "$scratch/hello"
"$scratch/hello" > /dev/null

echo "==> Installing Maylang $version into $prefix"
build/dev/bin/may-installer --bundle "$root/build/dev" --prefix "$prefix" --yes --no-modify-path --plain

# The installed copy must work without the checkout's sidecars.
(cd "$scratch" && MAYLANG_STDLIB="$prefix/current/stdlib" "$prefix/bin/mayc" "$root/examples/hello.may" -o "$scratch/installed")
"$scratch/installed" > /dev/null

if [ "$keep" -gt 0 ]; then
    current=$(basename "$(readlink -f "$prefix/current")")
    # Newest first by modification time; only nightlies are pruned.
    ls -1t "$prefix/releases" | grep -- '-nightly\.' | tail -n +"$((keep + 1))" | while read -r name; do
        if [ "$name" != "$current" ]; then
            rm -rf "${prefix:?}/releases/$name"
            echo "    removed old nightly $name"
        fi
    done
    python3 - "$prefix" <<'EOF'
import json, os, sys
prefix = sys.argv[1]
path = os.path.join(prefix, '.maylang-install.json')
if os.path.exists(path):
    data = json.load(open(path))
    data['releases'] = [r for r in data.get('releases', []) if os.path.isdir(os.path.join(prefix, 'releases', r))]
    with open(path + '.tmp', 'w') as out:
        json.dump(data, out, separators=(',', ':'))
    os.replace(path + '.tmp', path)
EOF
fi

echo "==> Installed: $("$prefix/bin/mayc" --version) ($version)"
echo "    selected release: $(readlink "$prefix/current")"
