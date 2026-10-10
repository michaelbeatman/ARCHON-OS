#!/bin/bash
# Stale Sockets & Daemon Locks bereinigen
rm -rf /root/.prime/agent/*.sock* /root/.prime/agent/logs/*.sock* /tmp/*.sock /tmp/prime* 2>/dev/null || true
pkill -9 -f "prime-agent.*daemon" 2>/dev/null || true

# ttyd starten mit robuster Shell-Schleife, die bei Beendigung sauber neu startet
exec ttyd -p 7681 -W -t titleFixed="Prime Agent" bash -c '
  while true; do
    rm -rf /root/.prime/agent/*.sock* /root/.prime/agent/logs/*.sock* /tmp/*.sock /tmp/prime* 2>/dev/null || true
    pkill -9 -f "prime-agent.*daemon" 2>/dev/null || true
    prime-agent "$@" || true
    echo ""
    echo "--- Prime Agent Session beendet. Drücke [Enter] für Neustart ---"
    read -r
  done
'
