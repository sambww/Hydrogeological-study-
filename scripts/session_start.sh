#!/usr/bin/env bash
# Claude Code SessionStart hook: make the project runnable (venv + editable install) so tests and the CLI work.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv >/dev/null 2>&1 || exit 0
fi
if ! .venv/bin/python -c "import hydrostudy, numpy, docx, pytest" >/dev/null 2>&1; then
  .venv/bin/pip install -q --upgrade pip >/dev/null 2>&1 || true
  .venv/bin/pip install -q -e ".[dev]" >/dev/null 2>&1 || echo "hydrostudy: dependency install failed; run .venv/bin/pip install -e .[dev]"
fi
echo "hydrostudy: environment ready (.venv). Run .venv/bin/pytest or .venv/bin/hydrostudy run examples/black_oak_well_2"
