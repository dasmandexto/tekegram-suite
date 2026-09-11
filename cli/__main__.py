"""Точка входа: python -m cli [--env path] <module> [args...]"""
import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
