#!/usr/bin/env bash
# ==============================================================================
# [Archon OS] 1-Klick Update & Snapshot Sync (Linux / Ubuntu Homeserver)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "=============================================================================="
echo "🚀 [Archon OS] Starte System-Update..."
echo "=============================================================================="

# 1. Update & Snapshot über Python Engine
echo "📦 [1/3] Erstelle Snapshot & ziehe neuesten Stand von GitHub..."
if command -v python3 &> /dev/null; then
    python3 backend/system_updater.py --apply
elif command -v python &> /dev/null; then
    python backend/system_updater.py --apply
else
    docker exec ARCHON-OS python backend/system_updater.py --apply
fi

# 2. Container neu starten
echo "🔄 [2/3] Starte Container neu..."
if command -v docker &> /dev/null; then
    docker restart ARCHON-OS || docker compose up -d --remove-orphans archon-os
fi

# 3. Health-Check
echo "🩺 [3/3] Prüfe System-Gesundheit..."
sleep 3
if command -v curl &> /dev/null; then
    curl -sSf -H "X-Archon-Service-Token: $(cat /mnt/raid/AgenticOS-2026/data/.archon_service_token 2>/dev/null)" http://localhost:8501/api/v1/research/providers > /dev/null && echo "✅ Archon OS ist online!" || echo "⚠️ Container startet noch..."
fi

echo "=============================================================================="
echo "🎉 Update erfolgreich abgeschlossen!"
echo "=============================================================================="
