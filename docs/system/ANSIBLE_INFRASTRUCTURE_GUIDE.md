# Ansible Infrastructure as Code Guide (Archon OS 2026)

Dieser Leitfaden beschreibt die wiederholbare und automatisierte Bereitstellung von Archon OS Nodes mittels Ansible. Er ersetzt manuelle Setup-Skripte (`setup_homeserver.sh`, `setup_new_machine.sh`) durch deklarative Infrastructure-as-Code Playbooks.

---

## 1. Verzeichnisstruktur

```
ansible/
├── ansible.cfg                    # Zentrale Ansible-Konfiguration (sudo, timeouts, yaml stdout)
├── inventory/
│   └── hosts.ini                  # Zielsysteme (Localhost, Homeserver, Production)
├── playbooks/
│   └── site.yml                   # Haupt-Playbook zur Orchestrierung
└── roles/
    └── archon_node/
        ├── tasks/
        │   └── main.yml           # Idempotente Bereitstellungstasks
        └── vars/
            └── main.yml           # Standardpfade, Systempakete & Ports
```

---

## 2. Automatisierte Aufgaben der Rolle `archon_node`

1. **Systempakete & Prerequisites:**
   - Aktualisierung des Apt-Paket-Caches unter Debian/Ubuntu.
   - Installation essenzieller Pakete (`curl`, `git`, `rsync`, `jq`, `python3-venv`, etc.).
2. **Container Engine:**
   - Einrichtung des offiziellen Docker Apt-Repositories mit signiertem GPG-Schlüssel.
   - Installation von `docker-ce`, `docker-compose-plugin` und `containerd`.
   - Aktivierung des Docker Systemd-Dienstes und Hinzufügen des Deployment-Benutzers zur `docker`-Gruppe.
3. **Verzeichnis- & Rechtestruktur:**
   - Deklarative Erstellung aller Daten- und Laufzeitverzeichnisse (`/opt/data`, `/opt/archon-os/data`, `pocketbase`, `paperclip_data`, `obsidian_vault`, `~/.hermes`).
   - Berechtigungsabsicherung mit Least-Privilege-Rechten (`0775` / `0600` für `.env`).
4. **Konfiguration & Deployment:**
   - Sichere Kopie von `.env.example` nach `.env`, falls noch keine Konfiguration existiert.
   - Starten der Container-Landschaft mittels `docker compose -f docker-compose.dev.yml up -d`.
   - Automatisierter Healthcheck gegen `http://localhost:8501/health` mit Retry-Schleife.

---

## 3. Ausführung

### Lokale Ausführung (auf dem Node selbst)
```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/site.yml --limit local
```

### Remote Homeserver / Host bereitstellen
```bash
# 1. Verbindung und Host-Keys prüfen (Dry-Run / Syntax Check)
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/site.yml --syntax-check

# 2. Check-Modus (Simulation ohne Änderungen)
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/site.yml -l homeservers --check

# 3. Live-Rollout mit Sudo-Passwortabfrage
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/site.yml -l homeservers -K
```

---

## 4. Rollback & Fehlerbehebung

- **Docker-Socket Permission Denied:** Der Benutzer muss sich nach dem Hinzufügen zur Docker-Gruppe einmal ab- und wieder anmelden oder `newgrp docker` ausführen.
- **Port-Konflikte (8501, 5678, 8090):** Prüfen via `ss -tulpn | grep -E '8501|5678|8090'` und ggf. in `vars/main.yml` oder `.env` anpassen.
- **Idempotenz:** Jeder Schritt kann beliebig oft wiederholt ausgeführt werden, ohne bestehende Daten zu überschreiben.
