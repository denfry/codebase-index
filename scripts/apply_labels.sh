#!/usr/bin/env bash
# Create or update the repository labels from .github/labels.yml.
# Requires: gh (authenticated), python3 with PyYAML (installed by the dev extra).
#   scripts/apply_labels.sh                 # denfry/codebase-index
#   scripts/apply_labels.sh owner/repo      # another repository
set -euo pipefail

REPO="${1:-denfry/codebase-index}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABELS="$HERE/../.github/labels.yml"

python3 - "$LABELS" <<'PY' | while IFS=$'\t' read -r name color desc; do
import sys, yaml
for row in yaml.safe_load(open(sys.argv[1], encoding="utf-8")):
    print(f"{row['name']}\t{row['color']}\t{row.get('description', '')}")
PY
  echo "label: $name"
  gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
done
