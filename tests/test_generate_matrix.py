"""Tests for generate_matrix.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Allow importing generate_matrix from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))
import generate_matrix  # noqa: E402


class TestGetDefaultCombinations:
    """Tests for get_default_combinations()."""

    ALL = [
        "gcc/none", "gcc/asan", "gcc/tsan", "gcc/valgrind", "gcc/perfetto",
        "clang/none", "clang/asan", "clang/tsan", "clang/valgrind", "clang/perfetto",
    ]

    @pytest.mark.parametrize("event_name", ["push", "pull_request", "issue_comment", "workflow_dispatch"])
    def test_minimal_events_return_gcc_none(self, event_name: str) -> None:
        """Test that common events return gcc/none."""
        result = generate_matrix.get_default_combinations(event_name, self.ALL)
        assert result == ["gcc/none"]

    def test_schedule_returns_gcc_perfetto(self) -> None:
        """Test that schedule event returns gcc/perfetto."""
        result = generate_matrix.get_default_combinations("schedule", self.ALL)
        assert result == ["gcc/perfetto"]

    def test_unknown_event_returns_gcc_none(self) -> None:
        """Test that unknown events default to gcc/none."""
        result = generate_matrix.get_default_combinations("unknown_event", self.ALL)
        assert result == ["gcc/none"]


class TestMain:
    """Tests for main() via environment variable injection."""

    def _run_main(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, event: str, user_input: str = "", comment_body: str = "") -> list[dict[str, str]]:
        """Run main() with mocked environment variables and return the matrix."""
        output_file = tmp_path / "github_output"
        output_file.write_text("")
        monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        monkeypatch.setenv("USER_INPUT", user_input)
        monkeypatch.setenv("COMMENT_BODY", comment_body)
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        generate_matrix.main()
        content = output_file.read_text()
        matrix_line = next(l for l in content.splitlines() if l.startswith("matrix="))
        return json.loads(matrix_line.split("=", 1)[1])["include"]

    def test_no_input_pr_event(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test PR event with no input returns gcc/none."""
        result = self._run_main(monkeypatch, tmp_path, event="pull_request", user_input="")
        assert result == [{"compiler": "gcc", "sanitizer": "none"}]

    def test_no_input_schedule(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test schedule event with no input returns gcc/perfetto."""
        result = self._run_main(monkeypatch, tmp_path, event="schedule", user_input="")
        assert result == [{"compiler": "gcc", "sanitizer": "perfetto"}]

    def test_explicit_single_combo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test explicit single combination."""
        result = self._run_main(monkeypatch, tmp_path, event="pull_request", user_input="clang/asan")
        assert result == [{"compiler": "clang", "sanitizer": "asan"}]

    def test_explicit_multiple_combos(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test explicit multiple combinations."""
        result = self._run_main(monkeypatch, tmp_path, event="pull_request", user_input="gcc/none clang/tsan")
        # Result should be sorted
        assert sorted(result, key=lambda x: (x["compiler"], x["sanitizer"])) == sorted(
            [{"compiler": "gcc", "sanitizer": "none"}, {"compiler": "clang", "sanitizer": "tsan"}],
            key=lambda x: (x["compiler"], x["sanitizer"])
        )

    def test_all_modifier(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test 'all' modifier returns all combinations."""
        result = self._run_main(monkeypatch, tmp_path, event="pull_request", user_input="all")
        assert len(result) == 10

    def test_plus_modifier(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test '+' modifier adds to defaults."""
        result = self._run_main(monkeypatch, tmp_path, event="pull_request", user_input="+clang/none")
        # Should have gcc/none (default) + clang/none (added)
        assert sorted(result, key=lambda x: (x["compiler"], x["sanitizer"])) == sorted(
            [{"compiler": "gcc", "sanitizer": "none"}, {"compiler": "clang", "sanitizer": "none"}],
            key=lambda x: (x["compiler"], x["sanitizer"])
        )

    def test_minus_modifier(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test '-' modifier removes from defaults."""
        result = self._run_main(monkeypatch, tmp_path, event="pull_request", user_input="-gcc/none +clang/none")
        assert result == [{"compiler": "clang", "sanitizer": "none"}]

    def test_issue_comment_with_build_command(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test issue_comment event with @phlexbot build command."""
        result = self._run_main(
            monkeypatch, tmp_path,
            event="issue_comment",
            comment_body="@phlexbot build clang/asan"
        )
        assert result == [{"compiler": "clang", "sanitizer": "asan"}]

    def test_issue_comment_no_match(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test issue_comment event without build command uses default."""
        result = self._run_main(
            monkeypatch, tmp_path,
            event="issue_comment",
            comment_body="some other comment"
        )
        assert result == [{"compiler": "gcc", "sanitizer": "none"}]
