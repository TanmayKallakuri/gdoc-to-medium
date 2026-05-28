"""Medium backends implementing the MediumBackend Protocol (spec 5.3).

TokenBackend (REST API) ships first; PlaywrightBackend (web-UI fallback) is
added in a later wave. Both expose the same interface so the orchestrator is
agnostic to which is active.
"""

from __future__ import annotations

from .token_backend import (
    MediumClientError,
    PermanentMediumError,
    TokenBackend,
    TransientMediumError,
)

__all__ = [
    "MediumClientError",
    "PermanentMediumError",
    "TokenBackend",
    "TransientMediumError",
]
