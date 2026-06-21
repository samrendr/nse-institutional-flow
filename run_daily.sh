#!/usr/bin/env bash
# Daily wrapper invoked by com.fiveema.nseflow.plist at 18:45 IST.
# 1. fetch today's NSE data    2. regenerate dashboard
# 3. stage data/ + docs/        4. push to origin/main if anything changed
#
# Designed to fail soft: NSE rate-limits or weekend skips should not block
# the dashboard regeneration or future runs.

set -u
# Do NOT set -e — a failed NSE fetch should still allow dashboard rebuild.

# launchd ships an almost-empty PATH; restore the tools we need.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/usr/bin:/bin"

cd /Users/samrendrasingh/nse-flow-auto || exit 1

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') Daily NSE run ==="

# Sync first so we don't clobber commits made by the cloud cron or other machines.
echo "[0/4] Syncing with origin/main..."
git pull --rebase origin main || { echo "  pull failed; aborting"; exit 1; }

echo "[1/4] Fetching NSE data..."
# No --force: on weekends/holidays is_market_day() makes this a clean no-op,
# so we only ingest on the evenings NSE actually releases data (Mon-Fri).
python3 nse_institutional_flow.py || echo "  fetch returned non-zero; continuing"

echo "[2/4] Regenerating dashboard..."
python3 generate_dashboard.py || { echo "  dashboard generation failed; aborting push"; exit 1; }

echo "[3/4] Staging changes..."
git add data/ docs/

if git diff --staged --quiet; then
    echo "[4/4] No changes to commit. Done."
    exit 0
fi

git -c user.name="$(git config user.name)" \
    -c user.email="$(git config user.email)" \
    commit -m "auto: NSE flow update $(date '+%Y-%m-%d')"

echo "[4/4] Pushing to origin/main..."
git push origin main && echo "=== Done ===" || echo "=== Push failed (check gh auth) ==="
