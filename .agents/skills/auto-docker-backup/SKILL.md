---
name: auto-docker-backup
description: Automatisch synthetisierter Skill für 'Auto Docker Backup'.
version: 1.0.0
author: Archon OS Synthesizer (Pillar 7)
agent: hermes-coder
---

# Auto Docker Backup

## 1. Einsatzzweck & Trigger
Wird automatisch aktiviert bei: `Erstelle ein Docker-Backup aller Volumes`

## 2. Standardisierter Arbeitsablauf
1. Container stoppen
2. Tarball der Volumes erstellen
3. Auf NAS schieben

## 3. Benötigte Werkzeuge & Tools
- docker_cli
- local_filesystem

## 4. Best Practices & Qualitätssicherung
- Ergebnisse im Obsidian 2nd Brain dokumentieren.
- Bei Fehlern den Self-Correction Loop verwenden.
