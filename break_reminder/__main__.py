"""Entry point so that ``python -m break_reminder`` works.

The main loop lives in ``break_reminder.app``; this module is intentionally
thin so PyInstaller's ``--name`` and the dev-time ``-m`` invocation share
exactly the same wiring.
"""

from __future__ import annotations

import sys

from break_reminder.app import main

if __name__ == "__main__":
    sys.exit(main())
