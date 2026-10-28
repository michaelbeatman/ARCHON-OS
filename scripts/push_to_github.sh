#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$DIR"

COMMIT_MSG="$1"
if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Dev-Sync: $(date '+%Y-%m-%d %H:%M')"
fi

echo "========================================================"
echo "  Archon OS - Git Push zu GitHub"
echo "========================================================"
echo "[1/3] Füge Änderungen hinzu..."
git add -A

echo "[2/3] Erstelle Commit: '$COMMIT_MSG'..."
git commit -m "$COMMIT_MSG" || echo "[Hinweis] Keine neuen Änderungen zum Committen."

echo "[3/3] Pushe zu GitHub origin/main..."
git push origin main

echo ""
echo "[ERFOLG] Push abgeschlossen!"
