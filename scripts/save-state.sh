#!/usr/bin/env bash
set -euo pipefail
git add -- data/state.json data/meldungen.atom
if git diff --cached --quiet; then
  exit 0
fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "$1"
# Never force. An incompatible concurrent update must fail before mail can be sent.
git pull --rebase origin main
git push origin HEAD:main
