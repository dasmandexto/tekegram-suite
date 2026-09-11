"""Запуск: python -m web [--env path] [--host 127.0.0.1] [--port 8000]"""
from __future__ import annotations

import sys

from config import load_settings
from .server import run_web


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m web")
    parser.add_argument("--env", default=None, help="путь к .env")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    ns = parser.parse_args()

    settings = load_settings(ns.env)
    return run_web(settings, ["--host", ns.host, "--port", str(ns.port)])


if __name__ == "__main__":
    sys.exit(main())
