import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

ROUTINE_WORKFLOWS = [
    {
        "id": "b1c3f1e9b2d84f11",
        "name": "Archon Morning-Briefing Routine",
        "active": True,
        "nodes": [
            {
                "parameters": {
                    "rule": {
                        "interval": [
                            {
                                "field": "cronExpression",
                                "expression": "30 7 * * 1-5"
                            }
                        ]
                    }
                },
                "id": "cron-briefing",
                "name": "Schedule (07:30 Mo-Fr)",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [0, -80]
            },
            {
                "parameters": {
                    "httpMethod": "POST",
                    "path": "archon-morning-briefing",
                    "responseMode": "lastNode",
                    "options": {}
                },
                "id": "wh-briefing",
                "name": "Webhook On-Demand",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 100],
                "webhookId": "archon-morning-briefing"
            },
            {
                "parameters": {
                    "method": "POST",
                    "url": "http://ARCHON-OS:8501/api/system/standup/run",
                    "sendBody": False,
                    "options": {}
                },
                "id": "http-standup",
                "name": "Run Morning Standup",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [240, 0]
            },
            {
                "parameters": {
                    "method": "POST",
                    "url": "http://ARCHON-OS:8501/api/telegram/send",
                    "sendBody": True,
                    "specifyBody": "keypair",
                    "bodyParameters": {
                        "parameters": [
                            {
                                "name": "text",
                                "value": "={{ $json.briefing_markdown }}"
                            }
                        ]
                    },
                    "options": {}
                },
                "id": "http-telegram",
                "name": "Send Telegram Briefing",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [480, 0]
            },
            {
                "parameters": {
                    "assignments": {
                        "assignments": [
                            {
                                "id": "m1",
                                "name": "status",
                                "value": "success",
                                "type": "string"
                            },
                            {
                                "id": "m2",
                                "name": "routine",
                                "value": "morning_briefing",
                                "type": "string"
                            },
                            {
                                "id": "m3",
                                "name": "date",
                                "value": "={{ $json.date }}",
                                "type": "string"
                            },
                            {
                                "id": "m4",
                                "name": "message",
                                "value": "Morning-Briefing erfolgreich generiert und verteilt.",
                                "type": "string"
                            }
                        ]
                    },
                    "options": {}
                },
                "id": "set-briefing",
                "name": "Format Response",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [720, 0]
            }
        ],
        "connections": {
            "Schedule (07:30 Mo-Fr)": {
                "main": [
                    [
                        {
                            "node": "Run Morning Standup",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Webhook On-Demand": {
                "main": [
                    [
                        {
                            "node": "Run Morning Standup",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Run Morning Standup": {
                "main": [
                    [
                        {
                            "node": "Send Telegram Briefing",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Send Telegram Briefing": {
                "main": [
                    [
                        {
                            "node": "Format Response",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            }
        },
        "settings": {
            "executionOrder": "v1"
        }
    },
    {
        "id": "b1c3f1e9b2d84f12",
        "name": "Archon Weekly Maintenance & System-Audit",
        "active": True,
        "nodes": [
            {
                "parameters": {
                    "rule": {
                        "interval": [
                            {
                                "field": "cronExpression",
                                "expression": "0 23 * * 0"
                            }
                        ]
                    }
                },
                "id": "cron-audit",
                "name": "Schedule (So 23:00)",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [0, -80]
            },
            {
                "parameters": {
                    "httpMethod": "POST",
                    "path": "archon-weekly-audit",
                    "responseMode": "lastNode",
                    "options": {}
                },
                "id": "wh-audit",
                "name": "Webhook On-Demand",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 100],
                "webhookId": "archon-weekly-audit"
            },
            {
                "parameters": {
                    "method": "POST",
                    "url": "http://ARCHON-OS:8501/api/system/backup-db",
                    "sendBody": False,
                    "options": {}
                },
                "id": "http-backup",
                "name": "Create DB Backup",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [240, 0]
            },
            {
                "parameters": {
                    "method": "GET",
                    "url": "http://ARCHON-OS:8501/api/system/health",
                    "options": {}
                },
                "id": "http-health",
                "name": "Check System Health",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [480, 0]
            },
            {
                "parameters": {
                    "assignments": {
                        "assignments": [
                            {
                                "id": "w1",
                                "name": "status",
                                "value": "success",
                                "type": "string"
                            },
                            {
                                "id": "w2",
                                "name": "routine",
                                "value": "weekly_maintenance",
                                "type": "string"
                            },
                            {
                                "id": "w3",
                                "name": "system_health",
                                "value": "={{ $json.status }}",
                                "type": "string"
                            },
                            {
                                "id": "w4",
                                "name": "message",
                                "value": "Woechentliche System-Wartung und SQLite-Backup erfolgreich abgeschlossen.",
                                "type": "string"
                            }
                        ]
                    },
                    "options": {}
                },
                "id": "set-audit",
                "name": "Format Audit Response",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [720, 0]
            }
        ],
        "connections": {
            "Schedule (So 23:00)": {
                "main": [
                    [
                        {
                            "node": "Create DB Backup",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Webhook On-Demand": {
                "main": [
                    [
                        {
                            "node": "Create DB Backup",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Create DB Backup": {
                "main": [
                    [
                        {
                            "node": "Check System Health",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Check System Health": {
                "main": [
                    [
                        {
                            "node": "Format Audit Response",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            }
        },
        "settings": {
            "executionOrder": "v1"
        }
    },
    {
        "id": "b1c3f1e9b2d84f13",
        "name": "Archon RSS & News Watchdog Routine",
        "active": True,
        "nodes": [
            {
                "parameters": {
                    "rule": {
                        "interval": [
                            {
                                "field": "cronExpression",
                                "expression": "0 * * * *"
                            }
                        ]
                    }
                },
                "id": "cron-rss",
                "name": "Schedule (Stündlich)",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [0, -80]
            },
            {
                "parameters": {
                    "httpMethod": "POST",
                    "path": "archon-rss-watchdog",
                    "responseMode": "lastNode",
                    "options": {}
                },
                "id": "wh-rss",
                "name": "Webhook On-Demand",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 100],
                "webhookId": "archon-rss-watchdog"
            },
            {
                "parameters": {
                    "method": "POST",
                    "url": "http://ARCHON-OS:8501/api/inbox-watcher/scan-now",
                    "sendBody": False,
                    "options": {}
                },
                "id": "http-scan",
                "name": "Scan RSS Feeds",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [240, 0]
            },
            {
                "parameters": {
                    "assignments": {
                        "assignments": [
                            {
                                "id": "r1",
                                "name": "status",
                                "value": "success",
                                "type": "string"
                            },
                            {
                                "id": "r2",
                                "name": "routine",
                                "value": "rss_watchdog",
                                "type": "string"
                            },
                            {
                                "id": "r3",
                                "name": "message",
                                "value": "RSS & News Radar Scan abgeschlossen.",
                                "type": "string"
                            }
                        ]
                    },
                    "options": {}
                },
                "id": "set-rss",
                "name": "Format Scan Response",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [480, 0]
            }
        ],
        "connections": {
            "Schedule (Stündlich)": {
                "main": [
                    [
                        {
                            "node": "Scan RSS Feeds",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Webhook On-Demand": {
                "main": [
                    [
                        {
                            "node": "Scan RSS Feeds",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Scan RSS Feeds": {
                "main": [
                    [
                        {
                            "node": "Format Scan Response",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            }
        },
        "settings": {
            "executionOrder": "v1"
        }
    }
]

def run():
    print("=" * 60)
    print("DEPLOYMENT DER N8N ROUTINE-WORKFLOWS")
    print("=" * 60)

    # 1. Speichere JSON lokal
    json_path = Path("scripts/n8n_routine_workflows.json")
    json_path.write_text(json.dumps(ROUTINE_WORKFLOWS, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Routine-Workflows lokal gespeichert: {json_path}")

    # 2. Kopiere in n8n-Container
    copy_cmd = ["docker", "cp", str(json_path), "n8n:/home/node/n8n_routine_workflows.json"]
    res = subprocess.run(copy_cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print("[OK] Datei in Container n8n kopiert.")
    else:
        print(f"[FEHLER] docker cp: {res.stderr}")
        return

    # 3. Importiere in n8n
    import_cmd = [
        "docker", "exec", "n8n", "n8n", "import:workflow",
        "--input=/home/node/n8n_routine_workflows.json"
    ]
    res = subprocess.run(import_cmd, capture_output=True, text=True)
    print("[n8n Import Output]:")
    print(res.stdout or res.stderr)

    # 4. Synchronisiere activeVersionId & Webhooks
    subprocess.run(["docker", "cp", "scripts/activate_n8n_workflows.js", "n8n:/home/node/activate_workflows.js"])
    act_res = subprocess.run(["docker", "exec", "n8n", "node", "/home/node/activate_workflows.js"], capture_output=True, text=True)
    print("[Activation Output]:")
    print(act_res.stdout)

    # 5. n8n neu starten
    print("[INFO] Starte n8n neu zur Aktivierung...")
    subprocess.run(["docker", "restart", "n8n"], check=True)

    # 6. Verifiziere Workflows
    list_cmd = ["docker", "exec", "n8n", "n8n", "list:workflow"]
    res = subprocess.run(list_cmd, capture_output=True, text=True)
    print("\n[Aktuelle n8n Workflows]:")
    print(res.stdout)

    # 5. Aktualisiere n8n_workflows_bundle.json mit allen Workflows
    bundle_path = Path("scripts/n8n_workflows_bundle.json")
    current_bundle = []
    if bundle_path.exists():
        try:
            current_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except Exception:
            current_bundle = []
    
    # Merge routines into bundle
    existing_ids = {w["id"] for w in current_bundle if "id" in w}
    for rw in ROUTINE_WORKFLOWS:
        if rw["id"] not in existing_ids:
            current_bundle.append(rw)
            existing_ids.add(rw["id"])

    bundle_path.write_text(json.dumps(current_bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] n8n_workflows_bundle.json aktualisiert ({len(current_bundle)} Workflows).")

if __name__ == "__main__":
    run()
