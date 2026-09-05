"""cli/asb/install.py — instaladores de guardas e broker."""
from __future__ import annotations

from pathlib import Path


def guards(root: Path) -> int:
    raise NotImplementedError("install-guards nao implementado ainda")


def broker(root: Path) -> int:
    raise NotImplementedError("install-broker nao implementado ainda")
