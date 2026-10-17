#!/bin/sh
# Isolated installer regression checks; no compiler build or Python required.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
bundle="$work/source/maylang-1.2.3-x86_64-linux"
mkdir -p "$bundle/bin/runtime" "$bundle/stdlib"
for tool in mayc may mayfmt maypkg maylsp; do
    printf '#!/bin/sh\necho fixture\n' > "$bundle/bin/$tool"
done
for file in bin/runtime.may bin/native.may bin/prelude.may bin/runtime/core.may stdlib/prelude.may; do
    echo '// fixture' > "$bundle/$file"
done
echo '// external sidecar' > "$work/runtime.may"
rm "$bundle/bin/runtime.may"
ln -s "$work/runtime.may" "$bundle/bin/runtime.may"
echo 1.2.3 > "$bundle/VERSION"
archive="$work/release.tar.gz"
tar -czf "$archive" -C "$work/source" maylang-1.2.3-x86_64-linux
sha256sum "$archive" > "$archive.sha256"
root="$work/install with spaces and 'quote"
sh "$repo/dist/install.sh" "$archive" "$root"
. "$root/env.sh"
test "$(mayc)" = fixture
test "$MAYLANG_STDLIB" = "$root/current/stdlib"
original_path=$PATH
. "$root/env.sh"
test "$PATH" = "$original_path"
test -f "$root/current/bin/runtime/core.may"
sh "$repo/dist/install.sh" "$bundle" "$root"
selected="$root/maylang-1.2.3-x86_64-linux"
test "$(readlink "$root/current")" = "$selected"
# Removing the extracted source and external sidecar targets cannot break it.
rm -rf "$bundle"
rm "$work/runtime.may"
test "$(mayc)" = fixture
test -f "$root/current/bin/runtime/core.may"
test "$(cat "$root/current/bin/runtime.may")" = '// external sidecar'
# A bad checksum or incomplete bundle must preserve the selected installation.
echo bad > "$archive.sha256"
if sh "$repo/dist/install.sh" "$archive" "$root"; then exit 1; fi
test "$(readlink "$root/current")" = "$selected"
cp -R "$selected" "$bundle"
rm "$bundle/bin/runtime/core.may"
if sh "$repo/dist/install.sh" "$bundle" "$root"; then exit 1; fi
test "$(readlink "$root/current")" = "$selected"
mkdir "$work/conflicting"
mkdir "$work/conflicting/current"
echo '// fixture' > "$bundle/bin/runtime/core.may"
if sh "$repo/dist/install.sh" "$bundle" "$work/conflicting"; then exit 1; fi
echo 'PASS independent archive/bundle copies, source deletion, quoting, environment and failure preservation'
