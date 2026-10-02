#!/usr/bin/env python3
"""Create a sparse dedicated MayOS disk, preserving any existing image."""
from pathlib import Path
import sys

target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
try:
    with target.open("xb") as image:
        image.truncate(4 * 1024 * 1024)
    print(f"Created blank MayOS disk: {target}; initialise in the shell with format yes")
except FileExistsError:
    print(f"Preserving existing disk: {target}")
