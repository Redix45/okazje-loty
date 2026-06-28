#!/usr/bin/env bash
# Wrapper dla crona: skan -> commit deals.json -> push (Pages auto-odswiezy).
# DISCORD_WEBHOOK wstrzykuje cron (env). PROXY_FILE ustawiany tu.
set -u
cd "$(dirname "$0")" || exit 1

export PROXY_FILE="$PWD/proxies.txt"
DEPLOY_KEY="$HOME/.ssh/okazje_deploy"
GITSSH="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

echo "=== $(date '+%F %T') start ==="
python3 dealfinder.py

# Commit + push tylko gdy deals.json sie zmienil.
if ! git diff --quiet -- deals.json; then
  git add deals.json
  git commit -q -m "deals $(date '+%F %H%M')"
  GIT_SSH_COMMAND="$GITSSH" git push -q origin main && echo "pushed deals.json"
else
  echo "brak zmian w deals.json — nie pushuje"
fi
echo "=== $(date '+%F %T') koniec ==="
