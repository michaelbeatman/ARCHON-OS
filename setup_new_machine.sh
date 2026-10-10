#!/usr/bin/env bash
# =================================================================
# ARCHON OS / AGENTIC OS - UBUNTU 24.04 BOOTSTRAP & SETUP SKRIPT
# =================================================================
set -euo pipefail

echo "========================================================"
echo "    ARCHON OS - SETUP & INBETRIEBNAHME (UBUNTU 24.04)    "
echo "========================================================"

# 1. Systempakete & Docker Prerequisites prüfen
echo "[1/6] Prüfe System-Abhängigkeiten..."
if ! command -v docker &> /dev/null; then
  echo "Docker nicht gefunden. Installiere Docker..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg lsb-release
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "Docker erfolgreich installiert. (Falls Berechtigungsfehler auftreten, bitte einmal neu einloggen)."
fi

# 2. Ordnerstruktur erstellen
echo "[2/6] Erstelle Arbeits- & Datenverzeichnisse..."
mkdir -p data agent_workspace pocketbase/pb_data pocketbase-media/pb_data paperclip_data obsidian_vault static/avatars logs

# 3. Falls Backup vorhanden: Entpacken
if [ -f "archon_data_backup_latest.tar.gz" ]; then
  echo "[3/6] Entpacke bestehendes Daten-Backup (archon_data_backup_latest.tar.gz)..."
  tar -xzf archon_data_backup_latest.tar.gz -C .
elif [ -f "AgenticOS-2026-full-backup.zip" ]; then
  echo "[3/6] Entpacke AgenticOS-2026-full-backup.zip..."
  sudo apt-get install -y unzip > /dev/null 2>&1 || true
  unzip -q -o AgenticOS-2026-full-backup.zip -d .
elif ls archon_data_backup_*.tar.gz 1> /dev/null 2>&1; then
  LATEST_FILE=$(ls -t archon_data_backup_*.tar.gz | head -n1)
  echo "[3/6] Entpacke ${LATEST_FILE}..."
  tar -xzf "${LATEST_FILE}" -C .
else
  echo "[3/6] Kein Backup-Archiv gefunden. Starte mit Standard-Initialdaten."
fi

# 4. Hermes Home Setup
mkdir -p "$HOME/.hermes"
if [ -d "hermes_home" ]; then
  echo "Kopiere Hermes-Daten nach $HOME/.hermes..."
  cp -r hermes_home/* "$HOME/.hermes/"
  rm -rf hermes_home
fi

# 5. Umgebungskonfiguration (.env)
echo "[4/6] Konfiguriere .env..."
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "  -> .env aus .env.example erstellt. Bitte API-Keys bei Bedarf anpassen!"
  fi
fi

# 6. Berechtigungen setzen
echo "[5/6] Setze Datei- und Docker-Socket Berechtigungen..."
chmod -R u+rwX,go+rX data pocketbase pocketbase-media static manifests 2>/dev/null || true
chmod +x export_state.sh setup_new_machine.sh 2>/dev/null || true

# 7. Starten der Container im Entwicklermodus mit Hot-Reloading
echo "[6/6] Baue und starte Archon OS (Entwickler-Stack mit Hot-Reloading)..."
docker compose -f docker-compose.dev.yml up --build -d

echo ""
echo "========================================================"
echo "    ARCHON OS ERFOLGREICH GESTARTET!                   "
echo "========================================================"
echo ""
echo "Erreichbare Services:"
echo "  * Archon OS Mission Control: http://localhost:8501"
echo "  * n8n Automatisierung:       http://localhost:5678"
echo "  * Master Chat (Hermes):      http://localhost:8787"
echo "  * Paperclip Orchestrator:    http://localhost:3180"
echo "  * CRM & Kontakte:            http://localhost:3005"
echo "  * Pocketbase Media:          http://localhost:8092"
echo ""
echo "Logs live ansehen:"
echo "  docker compose -f docker-compose.dev.yml logs -f archon-os"
echo "========================================================"
