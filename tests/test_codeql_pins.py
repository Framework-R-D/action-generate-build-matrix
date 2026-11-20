"""Verify that coupled CodeQL actions stay on one immutable release."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


def codeql_references(source: str) -> list[tuple[str, str]]:
    """Return complete CodeQL action references from parsed workflow steps."""
    workflows = yaml.safe_load(source)
    references = []
    for job in workflows.get("jobs", {}).values():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if isinstance(uses, str) and uses.startswith("github/codeql-action/"):
                action, separator, reference = uses.removeprefix(
                    "github/codeql-action/"
                ).partition("@")
                references.append((action, reference if separator else ""))
    return references


class CodeQLPinTests(unittest.TestCase):
    """Reject independent component updates and mutable CodeQL references."""

    def test_one_immutable_release(self) -> None:
        """Require init, analyze, and any other CodeQL actions to share a commit."""
        directory = Path(__file__).resolve().parents[1] / ".github/workflows"
        files = [*directory.glob("*.yaml"), *directory.glob("*.yml")]
        references = [
            reference for path in files for reference in codeql_references(path.read_text())
        ]
        self.assertTrue({"init", "analyze"} <= {name for name, _ in references})
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for _, ref in references))
        self.assertEqual(len({ref for _, ref in references}), 1)

    def test_folded_uses_value_is_checked(self) -> None:
        """Folded YAML scalars remain complete CodeQL action references."""
        references = codeql_references(
            """jobs:
  codeql:
    steps:
      - uses: >-
          github/codeql-action/autobuild@v4
"""
        )
        self.assertEqual(references, [("autobuild", "v4")])
        self.assertFalse(re.fullmatch(r"[0-9a-f]{40}", references[0][1]))
