"""Anonymous stable identifiers used by local behavior analytics."""

from __future__ import annotations

import hashlib
import os.path as osp
import secrets


class IdentifierHasher:
    """Create stable, local-only identifiers without storing source paths."""

    def __init__(self, salt: bytes | None = None) -> None:
        """Initialize the hasher with a private process or persisted salt."""
        self._salt = salt or secrets.token_bytes(32)

    @property
    def salt(self) -> bytes:
        """Return the salt for a private persistence layer, never for logs."""
        return self._salt

    def _digest(self, namespace: str, value: str) -> str:
        """Hash a normalized value under a namespace."""
        material = f"{namespace}\0{value}".encode("utf-8")
        return hashlib.sha256(self._salt + material).hexdigest()[:32]

    def project_id(self, project_root: str) -> str:
        """Return a stable identifier for a project root."""
        normalized = osp.normcase(osp.abspath(osp.expanduser(project_root)))
        return f"project-{self._digest('project', normalized)}"

    def image_id(self, project_root: str, image_path: str) -> str:
        """Return a stable identifier for an image within a project."""
        project = osp.normcase(osp.abspath(osp.expanduser(project_root)))
        image = osp.normcase(osp.abspath(osp.expanduser(image_path)))
        try:
            relative = osp.relpath(image, project)
        except ValueError:
            relative = image
        return f"image-{self._digest('image', relative)}"


def new_session_id(prefix: str) -> str:
    """Return a non-guessable identifier for a runtime session."""
    return f"{prefix}-{secrets.token_hex(16)}"
