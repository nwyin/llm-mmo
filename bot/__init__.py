"""Discord front-end for a markdown knowledge base + GitHub action agents."""

import os
import sys

# Let bot/ modules import each other flatly in every context: python -m bot, pytest, and smoke.py.
sys.path.insert(0, os.path.dirname(__file__))
