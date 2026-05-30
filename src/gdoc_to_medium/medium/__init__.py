"""Medium backends implementing the MediumBackend Protocol (spec 5.3).

TokenBackend (REST API) is the legacy fast-lane for users who already hold a pre-2025
integration token. PlaywrightBackend (web-UI automation) is the path that works without
a token — the default for new users, since Medium stopped issuing tokens in Jan 2025.
Both expose the same interface so the orchestrator is agnostic to which is active.
"""

from __future__ import annotations

from .playwright_backend import (
    PlaywrightBackend,
    PlaywrightSessionError,
    PlaywrightUIError,
)
from .token_backend import (
    MediumClientError,
    PermanentMediumError,
    TokenBackend,
    TransientMediumError,
)

__all__ = [
    "MediumClientError",
    "PermanentMediumError",
    "PlaywrightBackend",
    "PlaywrightSessionError",
    "PlaywrightUIError",
    "TokenBackend",
    "TransientMediumError",
]
