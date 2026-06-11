"""Smoke test for generate_matrix module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow importing generate_matrix from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

import generate_matrix  # noqa: F401


def test_import() -> None:
    """Verify that generate_matrix can be imported."""
    assert generate_matrix is not None
