"""Enable `python -m gdoc_to_medium` (spec 9: Task Scheduler invokes this)."""

from __future__ import annotations

from .cli import main

raise SystemExit(main())
