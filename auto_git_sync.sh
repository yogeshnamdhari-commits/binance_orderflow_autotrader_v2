#!/bin/bash
# Auto-sync V20 project to origin/feature/v20-market-making with validation.
# Skips secrets and files >50MB (GitHub 100MB hard limit; captures events.jsonl are 138-392MB).
set -euo pipefail

REPO="/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2"
BRANCH="feature/v20-market-making"
MAX_BYTES=52428800  # 50MB

cd "$REPO"

CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
    echo "BLOCKED: current branch is $CURRENT_BRANCH, expected $BRANCH"
    exit 1
fi

# 1. Secret filename scan on working tree changes (before staging).
if git status --porcelain | grep -Ei '(\.env$|\.env\.local|\.pem$|\.key$|credentials|secrets?|apikey|private.*key)' >/dev/null 2>&1; then
    echo "BLOCKED: possible secret file detected in working tree:"
    git status --porcelain | grep -Ei '(\.env$|\.env\.local|\.pem$|\.key$|credentials|secrets?|apikey|private.*key)'
    exit 1
fi

# 2. Nothing changed.
if [[ -z "$(git status --porcelain)" ]]; then
    exit 0
fi

# 3. Stage everything git does not ignore.
git add -A

# 4. Unstage secrets if they somehow got staged (defense in depth; .env is gitignored but check anyway).
if git diff --cached --name-only | grep -Ei '(\.env$|\.env\.local|\.pem$|\.key$|credentials|secrets?|apikey)' >/dev/null 2>&1; then
    echo "BLOCKED: secret file staged, resetting:"
    git diff --cached --name-only | grep -Ei '(\.env$|\.env\.local|\.pem$|\.key$|credentials|secrets?|apikey)'
    git reset >/dev/null
    exit 1
fi

# 5. Unstage oversized files (>50MB) so push cannot be rejected; keep them local.
OVERSIZED="$(git diff --cached --name-only | while read -r f; do
    if [[ -f "$f" ]]; then
        size=$(wc -c < "$f" | tr -d ' ')
        if [[ "$size" -gt "$MAX_BYTES" ]]; then echo "$f ($size bytes)"; fi
    fi
done)"
if [[ -n "$OVERSIZED" ]]; then
    echo "SKIP large files (>50MB, kept local, not pushed):"
    echo "$OVERSIZED"
    echo "$OVERSIZED" | sed 's/ (.*//' | while read -r f; do git reset -q -- "$f" || true; done
fi

# 6. If nothing left after unstaging large files, stop (large data only changed).
if [[ -z "$(git diff --cached --name-only)" ]]; then
    echo "Only large/local files changed; nothing to commit."
    exit 0
fi

# 7. Python syntax check on staged .py files.
STAGED_PY="$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)"
if [[ -n "$STAGED_PY" ]]; then
    echo "$STAGED_PY" | while read -r f; do
        python3 -m py_compile "$f" || { echo "BLOCKED: syntax error in $f"; git reset >/dev/null; exit 1; }
    done
fi

# 8. MM smoke test: imports must resolve.
if ! python3 -c "import app.mm.backtest, app.mm.fill_sim, app.mm.config" 2>/dev/null; then
    echo "BLOCKED: app.mm smoke import failed; resetting commit."
    git reset >/dev/null
    exit 1
fi

# 9. Commit + push.
git commit -m "auto: sync project $(date '+%Y-%m-%d %H:%M:%S %z')" || true
git push origin "$BRANCH"

echo "GitHub sync completed: $(git rev-parse --short HEAD)"
