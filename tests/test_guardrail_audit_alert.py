"""Exercise the guardrail's actual shell script without GitHub or Slack access."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/guardrail-audit-alert.yaml"
MERGED_AT = "2026-10-29T19:00:00Z"
PUSH_TIME = 1793300400
REPOSITORY = "example/action"


def workflow_script() -> str:
    """Extract the script so tests cannot drift from the workflow implementation."""
    pattern = r"^        run: \|\n((?:          .*\n|\n)+)"
    match = re.search(pattern, WORKFLOW.read_text(), re.M)
    if match is None:
        raise AssertionError("Could not find the guardrail workflow script")
    return textwrap.dedent(match.group(1))


def merged_pr(**overrides: Any) -> dict[str, Any]:
    """Build a matching PR record independently of the repository under test."""
    return {
        "merged_at": MERGED_AT,
        "merge_commit_sha": "sha",
        "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
    } | overrides


class GuardrailAlertTests(unittest.TestCase):
    """Check merge classification, failure handling, and payload safety."""

    def run_script(
        self, pages: str | None = None, **overrides: str
    ) -> tuple[subprocess.CompletedProcess[str], list[str] | None, str | None]:
        """Run with isolated API and delivery stubs, returning their captured calls."""
        with tempfile.TemporaryDirectory(prefix="guardrail-test-") as temp_dir:
            temp_path = Path(temp_dir)
            gh_args, curl_args = temp_path / "gh-args", temp_path / "curl-args"
            gh = temp_path / "gh"
            gh.write_text(
                '#!/bin/sh\nprintf "%s" "$*" > "$GH_ARGS"\n'
                'printf "%s" "$PR_PAGES"\nexit "$GH_EXIT"\n'
            )
            gh.chmod(0o755)
            curl = temp_path / "curl"
            curl.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                'with open(os.environ["CURL_ARGS"], "w") as stream:\n'
                "    json.dump(sys.argv[1:], stream)\n"
                'print("ok")\nprint(os.environ["HTTP_STATUS"])\n'
                'sys.exit(int(os.environ["CURL_EXIT"]))\n'
            )
            curl.chmod(0o755)
            pr_pages = pages if pages is not None else json.dumps([[merged_pr()]])
            environment = (
                os.environ
                | {
                    "PATH": f"{temp_dir}:{os.environ['PATH']}",
                    "PR_PAGES": pr_pages,
                    "GH_ARGS": str(gh_args),
                    "CURL_ARGS": str(curl_args),
                    "GH_EXIT": "0",
                    "CURL_EXIT": "0",
                    "HTTP_STATUS": "200",
                    "GH_TOKEN": "test-token",
                    "SLACK_URL": "https://example.invalid",
                    "COMMIT_MSG": "test",
                    "PUSH_SHA": "sha",
                    "FORCED_PUSH": "false",
                    "PUSHED_AT": str(PUSH_TIME),
                    "REPO_NAME": REPOSITORY,
                    "ACTOR": "test",
                }
                | overrides
            )
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", workflow_script()],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            return (
                result,
                json.loads(curl_args.read_text()) if curl_args.exists() else None,
                gh_args.read_text() if gh_args.exists() else None,
            )

    def test_recent_merges_and_window_boundaries(self) -> None:
        """Normalize epoch/ISO event times and expose the bounded heuristic."""
        for pushed_at, alerts in [
            (str(PUSH_TIME), False),
            (MERGED_AT, False),
            (str(PUSH_TIME - 60), False),
            (str(PUSH_TIME + 60), False),
            (str(PUSH_TIME - 61), True),
            (str(PUSH_TIME + 61), True),
            (str(PUSH_TIME + 600), True),
            (str(PUSH_TIME + 86400), True),
        ]:
            with self.subTest(pushed_at=pushed_at):
                result, curl, gh = self.run_script(PUSHED_AT=pushed_at)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(curl is not None, alerts)
                self.assertEqual(
                    gh, f"api --paginate --slurp repos/{REPOSITORY}/commits/sha/pulls"
                )

    def test_queue_delays_and_reruns_do_not_change_event_time(self) -> None:
        """Runner timing must not replace the captured push timestamp."""
        for started in ["2026-10-29T19:16:00Z", "2026-10-30T19:00:00Z"]:
            with self.subTest(started=started):
                result, curl, _ = self.run_script(RUN_STARTED_AT=started)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(curl)

    def test_pr_identity_and_pagination(self) -> None:
        """Require a merged PR's resulting SHA and this repository's main branch."""
        other_branch = {"ref": "other", "repo": {"full_name": REPOSITORY}}
        other_repo = {"ref": "main", "repo": {"full_name": "other/action"}}
        for pages, alerts in [
            ([], True),
            ([[]], True),
            ([[merged_pr(merged_at=None)]], True),
            ([[merged_pr(merge_commit_sha="other")]], True),
            ([[merged_pr(base=other_branch)]], True),
            ([[merged_pr(base=other_repo)]], True),
            ([[], [merged_pr()]], False),
            ([[merged_pr(merged_at=None)], [merged_pr()]], False),
        ]:
            with self.subTest(pages=pages):
                result, curl, _ = self.run_script(json.dumps(pages))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(curl is not None, alerts)

    def test_forced_push_alerts_without_lookup(self) -> None:
        """A force push never earns a PR exemption, including bot pushes."""
        result, curl, gh = self.run_script(
            FORCED_PUSH="true", GH_EXIT="1", ACTOR="dependabot[bot]", PUSHED_AT=""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(curl)
        self.assertIsNone(gh)

    def test_missing_or_invalid_event_time_alerts(self) -> None:
        """Unavailable correlation evidence must not suppress delivery."""
        for pushed_at in ["", "null", "invalid"]:
            with self.subTest(pushed_at=pushed_at):
                result, curl, gh = self.run_script(PUSHED_AT=pushed_at)
                self.assertEqual(result.returncode, 0)
                self.assertIsNotNone(curl)
                self.assertIsNone(gh)
                self.assertIn("::warning::", result.stdout)

    def test_missing_webhook_fails_even_for_pr_merge(self) -> None:
        """Detect configuration errors before the successful-merge early exit."""
        result, curl, gh = self.run_script(SLACK_URL="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SLACK_WEBHOOK_URL is not configured", result.stderr)
        self.assertIsNone(curl)
        self.assertIsNone(gh)

    def test_lookup_errors_fail(self) -> None:
        """API and malformed-response failures remain visible workflow failures."""
        for overrides in [{"GH_EXIT": "1"}, {"PR_PAGES": "invalid"}]:
            with self.subTest(overrides=overrides):
                result, curl, _ = self.run_script(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(curl)

    def test_slack_requires_http_200(self) -> None:
        """Reject redirects, unexpected successful statuses, and delivery failures."""
        for status, exit_code in [
            ("200", "0"),
            ("204", "0"),
            ("301", "0"),
            ("302", "0"),
            ("307", "0"),
            ("308", "0"),
            ("400", "22"),
            ("000", "7"),
        ]:
            with self.subTest(status=status):
                result, curl, _ = self.run_script(
                    "[[]]",
                    HTTP_STATUS=status,
                    CURL_EXIT=exit_code,
                )
                self.assertEqual(result.returncode == 0, status == "200")
                self.assertIsNotNone(curl)

    def test_payload_escapes_untrusted_values(self) -> None:
        """Messages and actor names stay data rather than executable shell input."""
        message = 'quotes " and \\ backslashes\n$(exit 42) `exit 43`'
        result, curl, _ = self.run_script(
            "[[]]",
            COMMIT_MSG=message,
            ACTOR='actor"\\\n',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(curl)
        assert curl is not None
        payload = json.loads(curl[curl.index("--data") + 1])
        self.assertIn(message, payload["text"])
        self.assertIn('actor"\\\n', payload["text"])
        self.assertNotIn("--location", curl)

    def test_workflow_uses_real_event_context(self) -> None:
        """Catch the unsupported-context defect that shell-only tests cannot see."""
        content = WORKFLOW.read_text()
        self.assertIn("PUSHED_AT: ${{ github.event.repository.pushed_at }}", content)
        self.assertNotIn("github.run_started_at", content)
        self.assertIn("pull-requests: read", content)


if __name__ == "__main__":
    unittest.main()
