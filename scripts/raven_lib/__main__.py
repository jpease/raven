"""Entry point for ``python -m raven_lib``: delegates straight to ``cli.main``."""

from __future__ import annotations

import sys

from .cli import main

sys.exit(main())
