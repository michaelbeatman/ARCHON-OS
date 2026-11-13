#!/bin/sh
# Führt die Test-Suite im laufenden Archon-Container aus.
cd /mnt/raid/AgenticOS-2026 || exit 1
docker exec -w /app ARCHON-OS python3 -m pytest tests/ -q --no-header -p no:cacheprovider
