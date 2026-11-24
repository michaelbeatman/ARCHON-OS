import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "data" / ".archon_service_token"
ARCHON_HOST = "http://archon-os:8501"

# F-037: EINE kanonische Quelle fuer die Routine-Workflows. Frueher lagen die
# drei Routinen dreimal vor (JSON-Vorlage, inline in diesem Skript, Bundle) und
# drifteten bei Host-Gross-/Kleinschreibung und Token-Platzhalter auseinander.
# Die JSON-Datei ist jetzt die SSOT; alles andere wird daraus erzeugt.
ROUTINE_TEMPLATE_PATH = ROOT / "scripts" / "n8n_routine_workflows.json"
TOKEN_PLACEHOLDER = "__ARCHON_SERVICE_TOKEN__"


def _load_routine_workflows() -> list:
    """Laedt die kanonischen Routine-Workflows per json.load aus der SSOT."""
    with ROUTINE_TEMPLATE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)

# A/H5: Fail-closed HMAC-SHA256-Verifikation fuer die On-Demand-Webhooks.
# Der Secret kommt ausschliesslich aus ARCHON_WEBHOOK_HMAC_SECRET (in n8n via
# docker-compose vorhanden). Ohne Secret oder Signatur bricht der Code-Node ab,
# bevor ein privilegierter Endpoint (/api/system/..., /api/telegram/send,
# /api/inbox-watcher/scan-now) erreicht wird. Der Schedule-Trigger bleibt
# bewusst ohne diesen Node (lokal vertrauenswuerdig).
HMAC_VERIFY_JS = """// A/H5 + D06/HIGH: HMAC-SHA256 ueber den EXAKTEN kompakten Body.
// Bevorzugt: crypto.createHmac + crypto.timingSafeEqual (constant time).
// Fallback, falls der n8n-Task-Runner Built-ins blockt: reines JS-HMAC mit
// constant-time XOR-Vergleich. Beide Pfade sind fail-closed.
let _crypto = null;
try { _crypto = require('crypto'); } catch (_e) { _crypto = null; }
const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
const RR=(x,n)=>(x>>>n)|(x<<(32-n));
function sha(b){const n=b.length,L=n*8,t=Math.ceil((n+9)/64)*64,m=new Uint8Array(t);m.set(b);m[n]=0x80;const v=new DataView(m.buffer);v.setUint32(t-8,Math.floor(L/4294967296),false);v.setUint32(t-4,L>>>0,false);let H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];const w=new Uint32Array(64);for(let i=0;i<t;i+=64){for(let j=0;j<16;j++)w[j]=v.getUint32(i+j*4,false);for(let j=16;j<64;j++){const x=w[j-15],y=w[j-2];w[j]=(w[j-16]+(RR(x,7)^RR(x,18)^(x>>>3))+w[j-7]+(RR(y,17)^RR(y,19)^(y>>>10)))>>>0;}let[a,b,c,d,e,f,g,h]=H;for(let j=0;j<64;j++){const S1=RR(e,6)^RR(e,11)^RR(e,25),ch=(e&f)^(~e&g),t1=(h+S1+ch+K[j]+w[j])>>>0,S0=RR(a,2)^RR(a,13)^RR(a,22),maj=(a&b)^(a&c)^(b&c),t2=(S0+maj)>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}H=[(H[0]+a)>>>0,(H[1]+b)>>>0,(H[2]+c)>>>0,(H[3]+d)>>>0,(H[4]+e)>>>0,(H[5]+f)>>>0,(H[6]+g)>>>0,(H[7]+h)>>>0];}const o=new Uint8Array(32),ov=new DataView(o.buffer);for(let i=0;i<8;i++)ov.setUint32(i*4,H[i],false);return o;}
function hmacJs(key,msg){let k=key;if(k.length>64)k=sha(k);const kp=new Uint8Array(64);kp.set(k);const ip=new Uint8Array(64),op=new Uint8Array(64);for(let i=0;i<64;i++){ip[i]=kp[i]^0x36;op[i]=kp[i]^0x5c;}const inner=new Uint8Array(64+msg.length);inner.set(ip);inner.set(msg,64);const ih=sha(inner);const outer=new Uint8Array(96);outer.set(op);outer.set(ih,64);return sha(outer);}
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
// Exakt dieselbe kompakte Serialisierung wie der Sender:
// Python json.dumps(..., ensure_ascii=False, separators=(',',':')) == JSON.stringify(body).
const bodyBytes=(item.rawBody && item.rawBody.length)
  ? (item.rawBody instanceof Uint8Array ? item.rawBody : enc.encode(String(item.rawBody)))
  : enc.encode(JSON.stringify(body));
const got=Uint8Array.from(sig.slice(7).match(/../g).map(x=>parseInt(x,16)));
const want=(_crypto && typeof _crypto.createHmac==='function')
  ? new Uint8Array(_crypto.createHmac('sha256',secret).update(Buffer.from(bodyBytes)).digest())
  : hmacJs(enc.encode(secret),bodyBytes);
if(got.length!==want.length){throw new Error('Ungueltige Webhook-Signatur - Trigger abgelehnt.');}
let valid;
if(_crypto && typeof _crypto.timingSafeEqual==='function'){
  valid=_crypto.timingSafeEqual(Buffer.from(got),Buffer.from(want));
}else{
  let diff=0;for(let i=0;i<want.length;i++){diff|=got[i]^want[i];}
  valid=(diff===0);
}
if(!valid){throw new Error('Ungueltige Webhook-Signatur - Trigger abgelehnt.');}
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
    """B/H5 + D06/HIGH: archon-execution nie ohne HMAC-Empfaenger aktiv sein lassen.

    Der versionierte Receiver (stabile ID a7c3f1e9b2d84f6a) ist im Bundle
    aktiv und antwortet im `response`-Modus: HMAC-Fehler fuehren ueber den
    Error-Branch des Code-Nodes zu HTTP 401 statt zu einem vorzeitigen 200.
    Nachgeruestete Workflows werden auf denselben Stand gebracht.
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
        verifier = next(
            (
                n for n in nodes
                if n.get("name") == "Archon HMAC Verify"
                and "ARCHON_WEBHOOK_HMAC_SECRET" in str(n.get("parameters", {}).get("jsCode", ""))
            ),
            None,
        )
        if verifier is not None:
            # Bereits vorhanden: auf den aktuellen Stand normalisieren statt
            # still eine inaktive/onReceived-Variante durchzulassen.
            verifier.setdefault("parameters", {})["jsCode"] = HMAC_VERIFY_JS
            for n in wh_nodes:
                n.setdefault("parameters", {})["responseMode"] = "response"
            wf["active"] = True
            wf["id"] = "a7c3f1e9b2d84f6a"  # stabile, in der Doku gefuehrte ID
            continue
        wh = wh_nodes[0]
        wh_name = wh.get("name", "Webhook Ingest")
        # response/lastNode: HTTP-Status erst NACH der HMAC-Pruefung senden.
        wh.setdefault("parameters", {})["responseMode"] = "response"
        target = None
        try:
            target = wf["connections"][wh_name]["main"][0][0].get("node")
        except (KeyError, IndexError, TypeError):
            target = None
        nodes.append(_hmac_node(
            "hmac-verify-execution",
            "B/H5 + D06/HIGH: HMAC-SHA256 mit crypto.timingSafeEqual (Fallback: Constant-Time-XOR) fuer archon-execution; Fehler -> HTTP 401.",
        ))
        conns = wf.setdefault("connections", {})
        conns[wh_name] = {"main": [[{"node": "Archon HMAC Verify", "type": "main", "index": 0}]]}
        if target:
            conns["Archon HMAC Verify"] = {"main": [[{"node": target, "type": "main", "index": 0}]]}
        wf["active"] = True
        prior = str(wf.get("notes", "")).strip()
        wf["notes"] = (prior + " | " if prior else "") + (
            "B/H5 + D06/HIGH: aktiver HMAC-Empfaenger, stabile ID a7c3f1e9b2d84f6a, "
            "responseMode 'response' — Ablehnung liefert HTTP 401."
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


BUNDLE_PATH = ROOT / "scripts" / "n8n_workflows_bundle.json"


def _load_bundle_workflows() -> list:
    """Laedt die versionierten On-Demand-Workflows inkl. HMAC-Empfaenger (D06/HIGH)."""
    try:
        with BUNDLE_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _inject_service_token(workflows: list, token: str) -> list:
    """Nur an Archon-API-HTTP-Nodes den Token injizieren, Host korrigieren.

    C17/F-037: Dieses Skript hat frueher die tokenhaltige Vorlage
    `n8n_routine_workflows.json` mit tokenlosen AKTIVEN Workflows ueberschrieben.
    Heute ist die JSON-Datei die einzige Quelle (json.load in
    `_load_routine_workflows`); ohne Token brechen wir ab, statt ein
    funktionsloses/wirkungsloses Deployment zu erzeugen.

    A(2): Der Service-Token gehoert ausschliesslich an HTTP-Nodes, die den
    lokalen Archon-API-Endpunkt aufrufen — nicht an beliebige/externe
    httpRequest-Nodes (Sonst waere das Token ein Exfiltrationsrisiko bei
    spaeter ergaenzten Nodes).
    """
    for wf in workflows:
        for node in wf.get("nodes", []):
            params = node.get("parameters", {})
            url = params.get("url")
            if isinstance(url, str):
                # F-037: beide historischen Host-Schreibweisen auf die SSOT
                # zurueckfuehren (Gross-/Kleinschreibung war der Driftpunkt).
                for legacy in ("http://ARCHON-OS:8501", "http://archon-os:8501"):
                    if url.startswith(legacy):
                        params["url"] = ARCHON_HOST + url[len(legacy):]
                        break
            is_archon_api = str(params.get("url", "")).startswith(ARCHON_HOST)
            if node.get("type") == "n8n-nodes-base.httpRequest" and is_archon_api:
                params["sendHeaders"] = True
                headers = params.setdefault("headerParameters", {}).setdefault("parameters", [])
                token_header = next(
                    (h for h in headers if str(h.get("name", "")).lower() == "x-archon-service-token"),
                    None,
                )
                if token_header is None:
                    headers.append({"name": "X-Archon-Service-Token", "value": token})
                elif str(token_header.get("value", "")).strip() in ("", TOKEN_PLACEHOLDER):
                    # SSOT enthaelt nur den Platzhalter; beim Deployment wird
                    # er durch den echten Token ersetzt, beim Template durch
                    # denselben Platzhalter (nie ein echter Token im Repo).
                    token_header["value"] = token
    return workflows


def _prepare_workflows(token: str) -> list:
    """Alle 9 Workflows (3 Routinen + 6 On-Demand inkl. Receiver) mit echtem Token."""
    workflows = json.loads(json.dumps(_load_routine_workflows()))
    known = {wf.get("id") for wf in workflows}
    for wf in _load_bundle_workflows():
        if wf.get("id") not in known:
            workflows.append(json.loads(json.dumps(wf)))
            known.add(wf.get("id"))
    return _inject_service_token(workflows, token)


def _prepare_routine_template() -> list:
    """Nur die 3 Routine-Workflows mit Platzhalter (fuer die Bundle-SSOT)."""
    return _inject_service_token(json.loads(json.dumps(_load_routine_workflows())), TOKEN_PLACEHOLDER)


def run():
    print("=" * 60)
    print("DEPLOYMENT ALLER N8N WORKFLOWS (3 Routinen + 6 On-Demand/Receiver)")
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
    template = _prepare_routine_template()

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

    # 7. Bundle aktualisieren (nur wenn beschreibbar — im Container read-only)
    # F-037: das Bundle ist ein GENERIERTES Artefakt. Die Routine-Sektion wird
    # bei jedem Lauf komplett aus der SSOT (template) ersetzt — nie mehr
    # haendisch gepflegt, daher kein Drift mehr bei Host/Token-Platzhalter.
    bundle_path = ROOT / "scripts" / "n8n_workflows_bundle.json"
    try:
        current_bundle = []
        if bundle_path.exists():
            try:
                current_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            except Exception:
                current_bundle = []
        routine_ids = {rw["id"] for rw in template if "id" in rw}
        current_bundle = [w for w in current_bundle if w.get("id") not in routine_ids]
        current_bundle.extend(template)
        # B/H5: kein unauthentifizierter Execution-Bridge-Empfaenger im Bundle.
        current_bundle = _ensure_bridge_hmac_receiver(current_bundle)
        bundle_path.write_text(json.dumps(current_bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[OK] n8n_workflows_bundle.json aktualisiert ({len(current_bundle)} Workflows).")
    except OSError as exc:
        print(f"[INFO] Bundle nicht aktualisiert (read-only filesystem): {exc}")

if __name__ == "__main__":
    sys.exit(run() or 0)
