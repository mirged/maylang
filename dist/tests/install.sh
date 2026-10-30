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
for file in bin/native.may bin/prelude.may bin/runtime/math.may \
    bin/runtime/fat.may bin/runtime/fat_linux.may bin/runtime/fat_core.may stdlib/prelude.may; do
    echo '// fixture' > "$bundle/$file"
done
echo '// external sidecar' > "$work/native.may"
rm "$bundle/bin/native.may"
ln -s "$work/native.may" "$bundle/bin/native.may"
echo 1.2.3 > "$bundle/VERSION"
archive="$work/release.tar.gz"
# Release archives hold no links; a directory bundle may (it is dereferenced).
tar -chzf "$archive" -C "$work/source" maylang-1.2.3-x86_64-linux
sha256sum "$archive" > "$archive.sha256"
root="$work/install with spaces and 'quote"
sh "$repo/dist/install.sh" "$archive" "$root"
. "$root/env.sh"
test "$(mayc)" = fixture
test "$MAYLANG_STDLIB" = "$root/current/stdlib"
original_path=$PATH
. "$root/env.sh"
test "$PATH" = "$original_path"
test -f "$root/current/bin/runtime/fat.may"
sh "$repo/dist/install.sh" "$bundle" "$root"
selected="$root/maylang-1.2.3-x86_64-linux"
test "$(readlink "$root/current")" = "$selected"
# Removing the extracted source and external sidecar targets cannot break it.
rm -rf "$bundle"
rm "$work/native.may"
test "$(mayc)" = fixture
test -f "$root/current/bin/runtime/fat.may"
test "$(cat "$root/current/bin/native.may")" = '// external sidecar'
# A bad checksum or incomplete bundle must preserve the selected installation.
echo bad > "$archive.sha256"
if sh "$repo/dist/install.sh" "$archive" "$root"; then exit 1; fi
test "$(readlink "$root/current")" = "$selected"
cp -R "$selected" "$bundle"
rm "$bundle/bin/runtime/fat.may"
if sh "$repo/dist/install.sh" "$bundle" "$root"; then exit 1; fi
test "$(readlink "$root/current")" = "$selected"
mkdir "$work/conflicting"
mkdir "$work/conflicting/current"
echo '// fixture' > "$bundle/bin/runtime/fat.may"
if sh "$repo/dist/install.sh" "$bundle" "$work/conflicting"; then exit 1; fi
# Archives may hold only one bundle of regular files and directories: links,
# traversal, duplicates and extra roots are rejected before extraction.
echo '// secret' > "$work/outside"
chmod 600 "$work/outside"
hostile() {
    rm -rf "$work/hostile" "$work/hostile.tar.gz"
    mkdir -p "$work/hostile"
    cp -R "$selected" "$work/hostile/maylang-9.9.9-x86_64-linux"
    echo 9.9.9 > "$work/hostile/maylang-9.9.9-x86_64-linux/VERSION"
}
seal() { sha256sum "$work/hostile.tar.gz" > "$work/hostile.tar.gz.sha256"; }
reject() {
    seal
    if sh "$repo/dist/install.sh" "$work/hostile.tar.gz" "$root" 2> "$work/error"; then exit 1; fi
    grep -q "$1" "$work/error"
    test "$(readlink "$root/current")" = "$selected"
    test ! -e "$root/maylang-9.9.9-x86_64-linux"
    test "$(stat -c %a "$work/outside")" = 600
}
hostile
rm "$work/hostile/maylang-9.9.9-x86_64-linux/bin/mayc"
ln -s "$work/outside" "$work/hostile/maylang-9.9.9-x86_64-linux/bin/mayc"
tar -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux
reject 'links or special files'
hostile
rm "$work/hostile/maylang-9.9.9-x86_64-linux/bin/mayc"
ln -s ../../../outside "$work/hostile/maylang-9.9.9-x86_64-linux/bin/mayc"
tar -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux
reject 'links or special files'
hostile
ln "$work/hostile/maylang-9.9.9-x86_64-linux/bin/may" "$work/hostile/maylang-9.9.9-x86_64-linux/bin/hardlinked"
tar -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux
reject 'links or special files'
hostile
tar --hard-dereference -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux maylang-9.9.9-x86_64-linux/VERSION
reject 'duplicate entries'
hostile
mkdir "$work/hostile/extra"
echo extra > "$work/hostile/extra/file"
tar -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux extra
reject 'exactly one'
hostile
tar -P -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux/../maylang-9.9.9-x86_64-linux
reject 'unsafe paths'
hostile
tar -czf "$work/hostile.tar.gz" -C "$work/hostile" maylang-9.9.9-x86_64-linux
seal
sh "$repo/dist/install.sh" "$work/hostile.tar.gz" "$root" > /dev/null
test "$(readlink "$root/current")" = "$root/maylang-9.9.9-x86_64-linux"
echo 'PASS independent archive/bundle copies, source deletion, quoting, environment and failure preservation'
