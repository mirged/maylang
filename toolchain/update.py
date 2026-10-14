#!/usr/bin/env python3
"""Compatibility entry point; implementation lives in distribution/."""
import runpy
from pathlib import Path

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'distribution/update.py'), run_name='__main__')
