#!/usr/bin/env bash
# Clone benchmark targets at fixed commits into benchmarks/.cache/.
# Re-running is idempotent (skips already-cloned targets).
#
# Usage: ./benchmarks/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="${SCRIPT_DIR}/.cache"
mkdir -p "${CACHE_DIR}"

# Format: name|url|ref
TARGETS=(
  "requests|https://github.com/psf/requests|v2.32.3"
  "flask|https://github.com/pallets/flask|3.0.3"
  "django|https://github.com/django/django|5.1.4"
  "pandas|https://github.com/pandas-dev/pandas|v2.2.3"
  "sympy|https://github.com/sympy/sympy|sympy-1.13.3"
  "langgraph|https://github.com/langchain-ai/langgraph|1.1.9"
)

for entry in "${TARGETS[@]}"; do
  IFS='|' read -r name url ref <<< "$entry"
  dest="${CACHE_DIR}/${name}"
  if [[ -d "${dest}" ]]; then
    echo "[skip] ${name} (already exists at ${dest})"
    continue
  fi
  echo "[clone] ${name} @ ${ref}"
  git clone --depth 1 --branch "${ref}" "${url}" "${dest}"
done

echo "Done. Targets in ${CACHE_DIR}"
echo
echo "Next: install benchmark dependencies (needed for langgraph target):"
echo "  uv sync --group benchmarks"
