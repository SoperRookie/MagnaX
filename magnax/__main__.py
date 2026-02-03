#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MagnaX - Real-time performance monitoring tool for Android/iOS apps.

Usage:
    magnax [--host=HOST] [--port=PORT]
    python -m magnax [--host=HOST] [--port=PORT]

Examples:
    magnax                          # Start with default settings (localhost:50003)
    magnax --host=0.0.0.0 --port=8080  # Custom host and port
"""

import fire
from magnax.web import main as web_main


def main():
    """Entry point for the magnax command."""
    fire.Fire(web_main)


if __name__ == '__main__':
    main()
