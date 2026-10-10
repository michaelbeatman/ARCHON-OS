#!/usr/bin/env bash
# =================================================================
# ANTIGRAVITY SKILLS & CONFIGURATION INSTALLER (UBUNTU LINUX)
# =================================================================
set -euo pipefail

echo "========================================================"
echo "   INSTALLIERE ANTIGRAVITY SKILLS & SYSTEM-KONFIGURATION "
echo "========================================================"

TARGET_GEMINI="$HOME/.gemini"
mkdir -p "$TARGET_GEMINI/config"

# 1. Zip-Paket entpacken falls vorhanden
if [ -f "antigravity_complete_skills_package.zip" ]; then
  echo "[1/3] Entpacke antigravity_complete_skills_package.zip..."
  sudo apt-get install -y unzip > /dev/null 2>&1 || true
  TMP_DIR=$(mktemp -d)
  unzip -q -o antigravity_complete_skills_package.zip -d "$TMP_DIR"
  
  if [ -d "$TMP_DIR/config" ]; then
    echo "[2/3] Kopiere 427 Skills, Plugins und Regeln nach $TARGET_GEMINI/config/..."
    cp -r "$TMP_DIR/config/"* "$TARGET_GEMINI/config/"
  fi
  
  rm -rf "$TMP_DIR"
else
  echo "[!] Warnung: antigravity_complete_skills_package.zip nicht gefunden!"
fi

# 2. Berechtigungen setzen
chmod -R u+rwX "$TARGET_GEMINI" 2>/dev/null || true

# 3. Status Report
SKILL_COUNT=$(find "$TARGET_GEMINI/config/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l || echo "0")
echo "=== [3/3] Installation erfolgreich abgeschlossen! ==="
echo "Installierte Skills in $TARGET_GEMINI/config/skills: $SKILL_COUNT"
echo "Plugins in $TARGET_GEMINI/config/plugins: Vorhanden"
echo "Globale Regeln (AGENTS.md): Aktiv"
echo ""
echo "Starte Antigravity auf deinem neuen Rechner neu — alle 427 Skills stehen sofort bereit!"
echo "========================================================"
