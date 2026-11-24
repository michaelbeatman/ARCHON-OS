import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "data" / ".archon_service_token"
ARCHON_HOST = "http://archon-os:8501"

# A/H5: Fail-closed HMAC-SHA256-Verifikation fuer die On-Demand-Webhooks.
# Der Secret kommt ausschliesslich aus ARCHON_WEBHOOK_HMAC_SECRET (in n8n via
# docker-compose vorhanden). Ohne Secret oder Signatur bricht der Code-Node ab,
# bevor ein privilegierter Endpoint (/api/system/..., /api/telegram/send,
# /api/inbox-watcher/scan-now) erreicht wird. Der Schedule-Trigger bleibt
# bewusst ohne diesen Node (lokal vertrauenswuerdig).
HMAC_VERIFY_JS = """// A/H5: HMAC-SHA256 ohne require('crypto') - der n8n-Task-Runner erlaubt 'crypto' nicht.
// Secret nur aus $env.ARCHON_WEBHOOK_HMAC_SECRET (kein Default, kein Repo).
const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
const RR=(x,n)=>(x>>>n)|(x<<(32-n));
function sha(b){const n=b.length,L=n*8,t=Math.ceil((n+9)/64)*64,m=new Uint8Array(t);m.set(b);m[n]=0x80;const v=new DataView(m.buffer);v.setUint32(t-8,Math.floor(L/4294967296),false);v.setUint32(t-4,L>>>0,false);let H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];const w=new Uint32Array(64);for(let i=0;i<t;i+=64){for(let j=0;j<16;j++)w[j]=v.getUint32(i+j*4,false);for(let j=16;j<64;j++){const x=w[j-15],y=w[j-2];w[j]=(w[j-16]+(RR(x,7)^RR(x,18)^(x>>>3))+w[j-7]+(RR(y,17)^RR(y,19)^(y>>>10)))>>>0;}let[a,b,c,d,e,f,g,h]=H;for(let j=0;j<64;j++){const S1=RR(e,6)^RR(e,11)^RR(e,25),ch=(e&f)^(~e&g),t1=(h+S1+ch+K[j]+w[j])>>>0,S0=RR(a,2)^RR(a,13)^RR(a,22),maj=(a&b)^(a&c)^(b&c),t2=(S0+maj)>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}H=[(H[0]+a)>>>0,(H[1]+b)>>>0,(H[2]+c)>>>0,(H[3]+d)>>>0,(H[4]+e)>>>0,(H[5]+f)>>>0,(H[6]+g)>>>0,(H[7]+h)>>>0];}const o=new Uint8Array(32),ov=new DataView(o.buffer);for(let i=0;i<8;i++)ov.setUint32(i*4,H[i],false);return o;}
function hmac(key,msg){let k=key;if(k.length>64)k=sha(k);const kp=new Uint8Array(64);kp.set(k);const ip=new Uint8Array(64),op=new Uint8Array(64);for(let i=0;i<64;i++){ip[i]=kp[i]^0x36;op[i]=kp[i]^0x5c;}const inner=new Uint8Array(64+msg.length);inner.set(ip);inner.set(msg,64);const ih=sha(inner);const outer=new Uint8Array(96);outer.set(op);outer.set(ih,64);return sha(outer);}
const secret=String(($env&&$env.ARCHON_WEBHOOK_HMAC_SECRET)||'').trim();
if(!secret){throw new Error('ARCHON_WEBHOOK_HMAC_SECRET fehlt - Trigger abgelehnt (fail-closed).');}
const item=$input.first().json||{};
const hdrs={};for(const[k,v]of Object.entries(item.headers||{}))hdrs[k.toLowerCase()]=String(v);
const body=Object.prototype.hasOwnProperty.call(item,'body')?item.body:item;
const sig=String(hdrs['x-archon-webhook-signature']||'');
const alg=String(hdrs['x-archon-webhook-algorithm']||'');
if(alg&&alg!=='HMAC-SHA256'){throw new Error('Falscher HMAC-Algorithmus - Trigger abgelehnt.');}
if(!sig.startsWith('sha256=')||!/^[0-9a-fA-F]{64}$/.test(sig.slice(7))){throw new Error('Fehlende/ungueltige Webhook-Signatur - Trigger abgelehnt.');}
const enc=new TextEncoder();
const got=Uint8Array.from(sig.slice(7).match(/../g).map(x=>parseInt(x,16)));
const want=hmac(enc.encode(secret),enc.encode(JSON.stringify(body)));
if(got.length!==want.length){throw new Error('Ungueltige Webhook-Signatur - Trigger abgelehnt.');}
let diff=0;for(let i=0;i<want.length;i++){diff|=got[i]^want[i];}
if(diff!==0){throw new Error('Ungueltige Webhook-Signatur - Trigger abgelehnt.');}
return $input.all();"""


def _hmac_node(node_id: str, note: str) -> dict:
    """A/H5: HMAC-Verifier-Node zwischen Webhook und privilegiertem HTTP-Node."""
    return {
        "parameters": {"jsCode": HMAC_VERIFY_JS},
        "id": node_id,
        "name": "Archon HMAC Verify",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [120, 100],
        "notesInFlow": True,
        "notes": note,
    }


def _ensure_bridge_hmac_receiver(bundle):
    """B/H5: archon-execution nie ohne HMAC-Empfaenger aktiv sein lassen.

    Landet ein (z. B. aus der Live-n8n exportierter) Execution-Bridge-Workflow
    im Bundle, wird der Verifier nachgeruestet, der Webhook auf 'onReceived'
    gestellt und der Workflow bleibt bis zur Verifikation INAKTIV. Die
    Doku-Behauptung (H5) wird nicht angefasst — sie betrifft eine andere Datei.
    """
    for wf in bundle:
        nodes = wf.get("nodes", [])
        wh_nodes = [
            n for n in nodes
            if n.get("type") == "n8n-nodes-base.webhook"
            and (
                str(n.get("parameters", {}).get("path", "")) == "archon-execution"
                or n.get("webhookId") == "archon-execution"
            )
        ]
        if not wh_nodes:
            continue
        if any(
            n.get("name") == "Archon HMAC Verify"
            and "ARCHON_WEBHOOK_HMAC_SECRET" in str(n.get("parameters", {}).get("jsCode", ""))
            and "HMAC-SHA256" in str(n.get("parameters", {}).get("jsCode", ""))
            for n in nodes
        ):
            continue
        wh = wh_nodes[0]
        wh_name = wh.get("name", "Webhook Ingest")
        wh.setdefault("parameters", {})["responseMode"] = "onReceived"
        target = None
        try:
            target = wf["connections"][wh_name]["main"][0][0].get("node")
        except (KeyError, IndexError, TypeError):
            target = None
        nodes.append(_hmac_node(
            "hmac-verify-execution",
            "B/H5: nachgeruestete HMAC-Pruefung (Constant-Time-XOR-Vergleich) fuer archon-execution; Workflow bleibt bis zur Verifikation inaktiv.",
        ))
        conns = wf.setdefault("connections", {})
        conns[wh_name] = {"main": [[{"node": "Archon HMAC Verify", "type": "main", "index": 0}]]}
        if target:
            conns["Archon HMAC Verify"] = {"main": [[{"node": target, "type": "main", "index": 0}]]}
        wf["active"] = False
        prior = str(wf.get("notes", "")).strip()
        wf["notes"] = (prior + " | " if prior else "") + (
            "B/H5: HMAC-Empfaenger nachgeruestet; bis zur Verifikation der "
            "Live-Implementierung INAKTIV."
        )
    return bundle


def _load_service_token() -> str:
    """Service-Token aus ENV oder der lokalen Token-Datei (nie aus dem Repo)."""
    tok = os.environ.get("ARCHON_SERVICE_TOKEN", "").strip()
    if tok:
        return tok
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _prepare_workflows(token: str):
    """Nur an Archon-API-HTTP-Nodes den Token injizieren, Host korrigieren.

    C17: Dieses Skript hat frueher die tokenhaltige Vorlage
    `n8n_routine_workflows.json` mit tokenlosen AKTIVEN Workflows ueberschrieben.
    Ohne Token brechen wir ab, statt ein funktionsloses/wirkungsloses Deployment
    zu erzeugen.

    A(2): Der Service-Token gehoert ausschliesslich an HTTP-Nodes, die den
    lokalen Archon-API-Endpunkt aufrufen — nicht an beliebige/externe
    httpRequest-Nodes (Sonst waere das Token ein Exfiltrationsrisiko bei
    spaeter ergaenzten Nodes).
    """
    workflows = json.loads(json.dumps(ROUTINE_WORKFLOWS))
    for wf in workflows:
        for node in wf.get("nodes", []):
            params = node.get("parameters", {})
            url = params.get("url")
            if isinstance(url, str):
                params["url"] = url.replace("http://ARCHON-OS:8501", ARCHON_HOST)
            is_archon_api = str(params.get("url", "")).startswith(ARCHON_HOST)
            if node.get("type") == "n8n-nodes-base.httpRequest" and is_archon_api:
                params["sendHeaders"] = True
                headers = params.setdefault("headerParameters", {}).setdefault("parameters", [])
                if not any(
                    str(h.get("name", "")).lower() == "x-archon-service-token"
                    for h in headers
                ):
                    headers.append({"name": "X-Archon-Service-Token", "value": token})
    return workflows


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
            _hmac_node(
                "hmac-verify-briefing",
                "A/H5: Constant-Time-HMAC-Vergleich (XOR) gegen ARCHON_WEBHOOK_HMAC_SECRET. Nur signierte Webhook-Trigger erreichen /api/system/standup/run und /api/telegram/send; der Schedule-Trigger bleibt bewusst ohne diesen Node (vertrauenswuerdig).",
            ),
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
                            "node": "Archon HMAC Verify",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Archon HMAC Verify": {
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
            _hmac_node(
                "hmac-verify-audit",
                "A/H5: Constant-Time-HMAC-Vergleich (XOR) gegen ARCHON_WEBHOOK_HMAC_SECRET. Nur signierte Webhook-Trigger erreichen /api/system/backup-db und /api/system/health; der Schedule-Trigger bleibt bewusst ohne diesen Node (vertrauenswuerdig).",
            ),
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
                            "node": "Archon HMAC Verify",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Archon HMAC Verify": {
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
            _hmac_node(
                "hmac-verify-rss",
                "A/H5: Constant-Time-HMAC-Vergleich (XOR) gegen ARCHON_WEBHOOK_HMAC_SECRET. Nur signierte Webhook-Trigger erreichen /api/inbox-watcher/scan-now; der Schedule-Trigger bleibt bewusst ohne diesen Node (vertrauenswuerdig).",
            ),
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
                            "node": "Archon HMAC Verify",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Archon HMAC Verify": {
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

    # 0. C17: ohne Service-Token keine aktiven, tokenlosen Workflows deployen.
    token = _load_service_token()
    if not token:
        print(
            "FEHLER: Kein ARCHON_SERVICE_TOKEN gefunden (ENV oder data/.archon_service_token). "
            "Deployment abgebrochen — aktive Workflows ohne Token wuerden bei aktivierter "
            "Auth mit 401 scheitern."
        )
        return 1
    workflows = _prepare_workflows(token)
    # Repo-getrackte Dateien enthalten NUR den Platzhalter — nie den echten
    # Token. Das import_n8n_workflows.py ersetzt ihn bei Bedarf zur Laufzeit.
    template = _prepare_workflows("__ARCHON_SERVICE_TOKEN__")

    # 1. Alles NUR im temporaeren Verzeichnis: der gehaertete Container hat
    # ein read-only /app und darf keine Repo-Dateien beschreiben.
    runtime_dir = Path(tempfile.mkdtemp(prefix="archon_n8n_deploy_"))
    template_path = runtime_dir / "n8n_routine_workflows.template.json"
    template_path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    runtime_path = runtime_dir / "n8n_routine_workflows.json"
    runtime_path.write_text(json.dumps(workflows, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(runtime_path, 0o600)
    print(f"[OK] Template + Laufzeitdatei (0600) in {runtime_dir}")

    # 2. Kopiere in n8n-Container
    copy_cmd = ["docker", "cp", str(runtime_path), "n8n:/home/node/n8n_routine_workflows.json"]
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

    # 5. Bundle aktualisieren (nur wenn beschreibbar — im Container read-only)
    bundle_path = ROOT / "scripts" / "n8n_workflows_bundle.json"
    try:
        current_bundle = []
        if bundle_path.exists():
            try:
                current_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            except Exception:
                current_bundle = []
        existing_ids = {w["id"] for w in current_bundle if "id" in w}
        for rw in template:
            if rw["id"] not in existing_ids:
                current_bundle.append(rw)
                existing_ids.add(rw["id"])
        # B/H5: kein unauthentifizierter Execution-Bridge-Empfaenger im Bundle.
        current_bundle = _ensure_bridge_hmac_receiver(current_bundle)
        bundle_path.write_text(json.dumps(current_bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[OK] n8n_workflows_bundle.json aktualisiert ({len(current_bundle)} Workflows).")
    except OSError as exc:
        print(f"[INFO] Bundle nicht aktualisiert (read-only filesystem): {exc}")

if __name__ == "__main__":
    sys.exit(run() or 0)
