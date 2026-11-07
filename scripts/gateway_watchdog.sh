#!/bin/sh
# Wacht über die Hermes-Gateway-Instanz (Telegram-Bot + Dashboard).
# Startet den Container neu, wenn er nicht läuft. Loggt jeden Eingriff.
LOG=/mnt/raid/AgenticOS-2026/data/logs/gateway_watchdog.log
STAMP=$(date '+%Y-%m-%d %H:%M:%S')

STATUS=$(docker inspect -f '{{.State.Running}}' hermes-webui 2>/dev/null)

if [ "$STATUS" != "true" ]; then
    echo "$STAMP  hermes-webui nicht aktiv (status=$STATUS) — starte neu" >> "$LOG"
    docker start hermes-webui >> "$LOG" 2>&1
    sleep 5
    curl -s -o /dev/null --max-time 10 http://127.0.0.1:8787/ \
        && echo "$STAMP  Dashboard antwortet wieder" >> "$LOG" \
        || echo "$STAMP  WARNUNG: Dashboard antwortet nicht" >> "$LOG"
fi
