#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" == Darwin ]]; then
  printf '%s\n' "actionlint: ShellCheck skipped on Darwin due to actionlint's pipe deadlock; CI runs it on Linux." >&2
  exec actionlint -shellcheck= "$@"
fi

exec actionlint "$@"
