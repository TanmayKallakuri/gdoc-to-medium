"""Shared data shapes and the backend interface. Pure declarations, no logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DocRef:
    """A Google Doc in the Ready-to-Publish folder (spec 5.1)."""

    doc_id: str
    name: str


@dataclass(frozen=True)
class ImageRef:
    """An inline image the converter emitted as a placeholder for the orchestrator to resolve (spec 5.2)."""

    object_id: str
    content_uri: str | None = None
    alt: str = ""


@dataclass
class Metadata:
    """Post metadata extracted from the doc (spec 4)."""

    title: str
    tags: list[str] = field(default_factory=list)
    publish_status: str = "draft"


@dataclass(frozen=True)
class PostResult:
    """Result of creating a Medium post."""

    url: str


@runtime_checkable
class MediumBackend(Protocol):
    """The interface both TokenBackend and PlaywrightBackend implement (spec 5.3)."""

    def upload_image(self, data: bytes, content_type: str) -> str:
        """Upload image bytes and return the hosted Medium image URL."""
        ...

    def create_post(
        self, title: str, markdown: str, tags: list[str], publish_status: str
    ) -> PostResult:
        """Create a Medium post from markdown and return its URL."""
        ...
