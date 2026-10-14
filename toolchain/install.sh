#!/bin/sh
# Compatibility entry point for existing installation instructions.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$here/distribution/install.sh" "$@"
