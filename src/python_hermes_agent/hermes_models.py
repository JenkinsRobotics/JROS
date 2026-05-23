#!/usr/bin/env python3
"""
Hermes CLI: Model Selection Command

Usage:
    hermes models              # Interactive selection
    hermes models --list       # List all models
    hermes models --select     # Select and configure
"""

import sys
import os

# Add upstream to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'upstream'))

from scan_models import main as scan_main

if __name__ == "__main__":
    scan_main()
