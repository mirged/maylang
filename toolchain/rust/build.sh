#!/bin/sh
# Build the installed native mayc entirely from Rust, C and Maylang source.
set -eu
bootstrap_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$bootstrap_dir/../.." && pwd)
mayc_dir="$repo_dir/toolchain/mayc"
bin_dir="$mayc_dir/build/bin"
mkdir -p "$bin_dir"
scratch=$(mktemp -d "$bin_dir/bootstrap.XXXXXX")
trap 'rm -rf -- "$scratch"' 0

wire_runtime() {
    ln -sf "$mayc_dir/runtime.may" "$1/runtime.may"
    ln -sf "$mayc_dir/native.may" "$1/native.may"
    ln -sf "$repo_dir/stdlib/prelude.may" "$1/prelude.may"
    ln -sfn "$mayc_dir/runtime" "$1/runtime"
}
wire_runtime "$scratch"
wire_runtime "$bin_dir"
cd "$repo_dir"
cargo build --offline --locked --release -p may_bootstrap
target_dir=${CARGO_TARGET_DIR:-"$repo_dir/target"}
case "$target_dir" in
    /*) ;;
    *) target_dir="$repo_dir/$target_dir" ;;
esac
"$target_dir/release/may-bootstrap" "$mayc_dir/main.may" -o "$scratch/mayc_stage1"
"$scratch/mayc_stage1" "$mayc_dir/main.may" -o "$scratch/mayc_new"
mv "$scratch/mayc_new" "$bin_dir/mayc_new"
