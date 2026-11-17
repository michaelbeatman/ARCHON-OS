#!/usr/bin/env python3
"""Lokale DE->ES Engine (eigenes Wissen, KEIN API-Call) + Batch-Cache + Apply wie translate_manual.py."""
import json, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from scripts.translate_manual import should_skip_text, merge_adjacent_similar_runs, NS

# ---------- 1. Hand-Übersetzungen laden ----------
HAND = {}
for fn in ["hand_es_p1.json","hand_es_p2.json","hand_es_p3.json","hand_es_p4.json","hand_es_p5.json","hand_es_p6.json"]:
    p = os.path.join(BASE, "data", fn)
    if os.path.exists(p):
        HAND.update(json.load(open(p, encoding="utf-8")))
cand = json.load(open(os.path.join(BASE, "data", "hand_candidates.json"), encoding="utf-8"))
ID2SRC = {str(it["id"]): it["src"] for it in cand}
HAND_SRC2ES = {ID2SRC[k]: v for k, v in HAND.items() if k in ID2SRC}

# ---------- 2. Schutz-Spans ----------
PRODUCTS = ["Archon OS","Mission Control","Decision Engine","Showroom","Research Lab","Token Guard",
    "System Control Center","Hermes Core","OmniRoute","AnythingLLM","ChromaDB","PocketBase","Obsidian",
    "n8n","Caddy","Authelia","Hermes","Evey","Robert","Micha","Steffi Kieffer","Deep Research",
    "Zero-Trust","Zero Trust","Blue Ocean Strategy","Design Sprint","Double Diamond","Lean Startup",
    "Lean Canvas","Wardley Mapping","McKinsey 7S","Five Forces","Porter","OODA-Loop","OODA","OKR","OKRs",
    "Kotter","Ishikawa","Cynefin","Flywheel","PDCA","Demingkreis","Deming","TRIZ","FMEA","MECE","JTBD",
    "DMAIC","Six Sigma","AARRR","5-Why","Ansoff","BCG","GE-McKinsey","ADL","Hamel","Prahalad","Mintzberg",
    "Christensen","Osterwalder","Pigneur","Ries","Kotter","Snowden","Collins","Kim","Mauborgne","Bono",
    "Munger","Argyris","Marks","Taleb","Boyd","Klein","Knapp","Shell-Methode","Shell","BGB","HGB","VOB",
    "HOAI","DATEV","GoBD","DSGVO","GDPR","EU-MDR","FDA","REACH","CLP","KfW","ESG","BGB/HGB","EXTF",
    "HITL","RAG","CRAG","MCP","API","RBAC","TLS","AES","SHA-256","PBKDF2-HMAC-SHA256","PBKDF2","Argon2id",
    "HSTS","HTTPS","SSL","VPN","IP","TCP","UDP","HTTP","SMTP","IMAP","JSON","XML","YAML","CSV","PDF",
    "HTML","CSS","DOM","FTS5","RRF","WAL","SQLite","SQL","CRM","ERP","BI","KPI","KPIs","SLA","SLO","SOP",
    "POE","MVP","MMP","UVP","PVU","TAM","SAM","SOM","CAC","LTV","DCF","ARR","MRR","LTV/CAC","ROI","OKR",
    "AHP","VRIO","SWOT","DAFO","PESTEL","STEEPLE","NABC","CLEAR","STE100","AOS","SOUL","HITL","P0","P1",
    "P2","P3","P4","CEO","CHRO","CFO","CTO","CIO","COO","HR","IT","DB","KI","AI","LLM","GPU","CPU","RAM",
    "ROM","SSD","HDD","I/O","DNS","CDN","CI","CD","QA","UX","UI","CMS","DAM","PIM","DMP","CDP","DSP",
    "GEO","AEO","SEO","SEA","SaaS","PaaS","IaaS","IMAP","EPC-QR","QR","NFC","RFID","OCR","TTS","STT",
    "ASR","NLP","NLU","ML","DL","RL","GAN","VAE","RAG","LoRA","QLoRA","PEFT","RLHF","DPO","GRPO","SFT",
    "MoE","CoT","ToT","ReAct","RAG","CRAG","HyDE","RAPTOR","GraphRAG","BM25","HNSW","IVF","PQ","LSH",
    "ANNS","JWT","OAuth","OIDC","SAML","LDAP","SSO","MFA","2FA","TOTP","HOTP","FIDO","WebAuthn","PKI",
    "X.509","md5","sha1","sha256","AES-256","RSA","ECC","ChaCha20","Poly1305","TLS1.3","DTLS","QUIC",
    "WebRTC","WebSocket","SSE","gRPC","REST","SOAP","GraphQL","OpenAPI","AsyncAPI","MQTT","AMQP","Kafka",
    "NATS","Redis","RabbitMQ","ZeroMQ","WebDAV","CalDAV","CardDAV","FTP","SFTP","SCP","rsync","SSH",
    "RDP","VNC","X11","Wayland","GNOME","KDE","systemd","cron","Docker","Kubernetes","K8s","Helm",
    "Terraform","Ansible","Pulumi","Jenkins","GitLab","GitHub","Bitbucket","Jira","Confluence","Notion",
    "Slack","Teams","Discord","Telegram","WhatsApp","Signal","Matrix","Mattermost","Zulip","Rocket.Chat",
    "Linux","macOS","Windows","Ubuntu","Debian","Fedora","Arch","Android","iOS","Python","TypeScript",
    "JavaScript","Go","Rust","Java","C++","C#","PHP","Ruby","Swift","Kotlin","Dart","Flutter","React",
    "Vue","Angular","Svelte","Next.js","Nuxt","Django","Flask","FastAPI","NestJS","Express","Spring",
    "Rails","Laravel","PostgreSQL","MySQL","MariaDB","MongoDB","CouchDB","Cassandra","Neo4j","Weaviate",
    "Qdrant","Milvus","Pinecone","Elasticsearch","OpenSearch","Solr","Meilisearch","Typesense","Sonic",
    "Prometheus","Grafana","Loki","Tempo","Jaeger","Zipkin","OpenTelemetry","Datadog","NewRelic","Splunk",
    "Graylog","Fluentd","Fluent Bit","Logstash","Beats","Vector","Falco","Trivy","Grype","Syft","Cosign",
    "Sigstore","Vault","SOPS","age","Sealed Secrets","External Secrets","Cert-Manager","Let's Encrypt",
    "ACME","SPIFFE","SPIRE","OPA","Kyverno","Gatekeeper","Falco","Tetragon","Cilium","Calico","Istio",
    "Linkerd","Consul","Envoy","Traefik","NGINX","HAProxy","Caddy","Apache","Lighttpd","MinIO","S3",
    "GCS","Azure Blob","Backblaze","Wasabi","rclone","Restic","Borg","Duplicity","Bacula","Veeam",
]
LOCKED_RES = [
    r"https?://\S+", r"www\.\S+", r"`[^`]+`", r"\b[a-z][a-z0-9_]*(?:_[a-z0-9]+)+\b",
    r"\b[A-Za-z0-9_]*[a-z]+[A-Za-z0-9_]*(?:\.py|\.yaml|\.yml|\.json|\.toml|\.md|\.sh|\.sql|\.js|\.ts|\.env)\b",
    r"\b(?:[A-Za-z0-9_\-]+\/)+[A-Za-z0-9_\-\.]+\b", r"\b\d[\d\.\,\:\/\-\%]*\b",
    r"\[(?:Dein Zugriff|Prompt|[^\]]*)\]", r"\([\w\-\.\/]+\)",
]
LOCK_RE = re.compile("|".join(LOCKED_RES))
PROD_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, PRODUCTS), key=len, reverse=True)) + r")\b")

def mask(text):
    slots = []
    def put(m):
        slots.append(m.group(0)); return f"\x00{len(slots)-1}\x00"
    t = LOCK_RE.sub(put, text)
    t = PROD_RE.sub(put, t)
    return t, slots

def unmask(text, slots):
    def back(m):
        i = int(m.group(1)); return slots[i] if i < len(slots) else m.group(0)
    return re.sub(r"\x00(\d+)\x00", back, text)

# ---------- 3. Phrasen (längste zuerst) ----------
PH = {
"Schritt für Schritt":"paso a paso","schritt für schritt":"paso a paso",
"Praxis-Workflow":"flujo de trabajo práctico","praxis-workflow":"flujo de trabajo práctico",
"auf einen Blick":"de un vistazo","im Überblick":"de un vistazo","im überblick":"de un vistazo",
"steuert den":"controla el","steuert die":"controla la","steuert das":"controla el",
"ermöglicht es":"permite","ermöglicht dem":"permite al","sorgt für":"garantiza","sorgt dafür":"garantiza",
"stellt sicher":"garantiza","stellen sicher":"garantizan","gewährleistet":"garantiza",
"findet statt":"tiene lugar","findet automatisch statt":"tiene lugar automáticamente",
"kommt zum Einsatz":"se utiliza","kommen zum Einsatz":"se utilizan",
"wird automatisch":"se automáticamente","werden automatisch":"se automáticamente",
"nach dem neuesten Stand":"según el estado actual","auf dem neuesten Stand":"al día",
"im Hintergrund":"en segundo plano","im Vordergrund":"en primer plano",
"in Echtzeit":"en tiempo real","in echtzeit":"en tiempo real",
"zum Beispiel":"por ejemplo","zum beispiel":"por ejemplo","beispielsweise":"por ejemplo",
"das heißt":"es decir","das heisst":"es decir","mit anderen Worten":"en otras palabras",
"im Gegensatz zu":"a diferencia de","im Vergleich zu":"en comparación con","im Unterschied zu":"a diferencia de",
"im Falle von":"en caso de","im Fall von":"en caso de","für den Fall":"para el caso",
"in Bezug auf":"respecto a","mit Bezug auf":"con referencia a","in bezug auf":"respecto a",
"im Hinblick auf":"con vistas a","im hinblick auf":"con vistas a",
"im Rahmen":"en el marco","im Rahmen von":"en el marco de","im rahmen":"en el marco",
"im Zuge":"en el curso","im Zuge von":"en el curso de",
"auf der Grundlage":"sobre la base","auf Grundlage":"sobre la base",
"mit Hilfe von":"con ayuda de","mithilfe von":"con ayuda de","mit hilfe von":"con ayuda de",
"ohne dass":"sin que","ohne zu":"sin","anstatt zu":"en lugar de","statt zu":"en lugar de",
"um zu":"para","auf Knopfdruck":"con solo pulsar un botón","per Knopfdruck":"pulsando un botón",
"auf einen Klick":"con un clic","mit einem Klick":"con un clic",
"rund um die Uhr":"24/7","rund um die uhr":"24/7",
"am laufenden Band":"en serie","auf dem Laufenden":"al día",
"auf den Punkt gebracht":"en pocas palabras","kurz gesagt":"en pocas palabras","mit einem Wort":"en una palabra",
"lange Rede":"en resumen","langer Rede kurzer Sinn":"en resumen",
"im Großen und Ganzen":"en líneas generales","im grossen und ganzen":"en líneas generales",
"im Allgemeinen":"en general","im allgemeinen":"en general","im Wesentlichen":"esencialmente",
"im Detail":"en detalle","im Einzelnen":"en detalle","im einzelnen":"en detalle",
"unter anderem":"entre otros","unter anderem":"entre otros",
"vor allem":"sobre todo","insbesondere":"en particular","namentlich":"concretamente",
"sowohl als auch":"tanto como","sowohl":"tanto","weder noch":"ni",
"je nach":"según","je nachdem":"según corresponda","abhängig von":"dependiendo de",
"basierend auf":"basado en","gestützt auf":"apoyado en",
"im Gegensatz":"en cambio","dagegen":"en cambio","hingegen":"en cambio",
"darüber hinaus":"además","des Weiteren":"además","des weiteren":"además",
"darüberhinaus":"además","ferner":"además","zudem":"además","außerdem":"además",
"trotzdem":"sin embargo","dennoch":"sin embargo","allerdings":"no obstante",
"jedoch":"sin embargo","aber":"pero","sondern":"sino","denn":"pues",
"deshalb":"por eso","daher":"por ello","darum":"por eso","deswegen":"por eso",
"folglich":"en consecuencia","infolgedessen":"en consecuencia","demzufolge":"en consecuencia",
"somit":"así pues","also":"así pues","mithin":"por tanto",
"vorausgesetzt":"siempre que","angenommen":"suponiendo","gesetzt den Fall":"suponiendo",
"falls":"si","sofern":"siempre que","soweit":"en la medida en que","insofern":"en tanto",
"obwohl":"aunque","obgleich":"aunque","wenngleich":"aunque","auch wenn":"aunque",
"während":"mientras/durante","waehrend":"mientras/durante","währenddessen":"entretanto",
"bevor":"antes de","bevor":"antes de que","nachdem":"tras","sobald":"en cuanto",
"sowie":"así como","sowohl":"tanto","sowohl als auch":"tanto como",
"entweder oder":"o bien","entweder":"o bien","bzw":"resp.","beziehungsweise":"respectivamente",
"das bedeutet":"esto significa","dies bedeutet":"esto significa",
"mit einem Wort":"en una palabra","genau genommen":"en sentido estricto",
"streng genommen":"en sentido estricto","im engeren Sinne":"en sentido estricto",
"im weiteren Sinne":"en sentido amplio","im weitesten Sinne":"en sentido amplio",
"kurz gesagt":"en pocas palabras","langfristig":"a largo plazo","mittelfristig":"a medio plazo","kurzfristig":"a corto plazo",
"früher oder später":"tarde o temprano","frueher oder spaeter":"tarde o temprano",
"Tag für Tag":"día a día","Schritt für Schritt":"paso a paso",
"oben genannten":"antes mencionado","unten genannten":"abajo mencionado",
"oben genannte":"antes mencionada","wie oben beschrieben":"como se describe arriba",
"wie unten beschrieben":"como se describe abajo","wie folgt":"como sigue",
"folgende":"siguiente","folgender":"siguiente","folgendes":"siguiente",
"im Folgenden":"a continuación","im folgenden":"a continuación",
"zusammenfassend":"en resumen","abschließend":"para concluir","abschliessend":"para concluir",
"nicht nur sondern auch":"no solo sino también",
"an erster Stelle":"en primer lugar","an zweiter Stelle":"en segundo lugar",
"zum einen":"por un lado","zum anderen":"por otro lado",
"einerseits":"por un lado","andererseits":"por otro lado",
"darüber":"sobre ello/encima","darunter":"bajo ello/debajo","davor":"ante ello/antes",
"danach":"después/tras ello","dabei":"en ello/junto a ello","dafür":"para ello",
"dagegen":"en cambio/contra ello","dahinter":"tras ello","daneben":"junto a ello",
"daraus":"de ello","darin":"en ello","darauf":"sobre ello","daraus folgt":"de ello se sigue",
"hierbei":"en esto/aquí","hierbei handelt es sich":"se trata de",
"dabei handelt es sich":"se trata de","es handelt sich um":"se trata de",
"handelt es sich um":"se trata de","handelt von":"trata de",
"geht es um":"se trata de","geht über":"va más allá de",
"muss beachtet werden":"debe tenerse en cuenta","ist zu beachten":"debe tenerse en cuenta",
"zu beachten ist":"debe tenerse en cuenta","bitte beachten":"téngase en cuenta",
"zu berücksichtigen":"a tener en cuenta","gilt es zu":"hay que",
"lässt sich":"se puede","laesst sich":"se puede","lassen sich":"se pueden",
"findet Anwendung":"se aplica","findet Verwendung":"se utiliza",
"steht zur Verfügung":"está disponible","stehen zur Verfügung":"están disponibles",
"zur Verfügung stellen":"poner a disposición","zur Verfügung steht":"está disponible",
"in Frage kommen":"entran en consideración","kommt in Frage":"entra en consideración",
"in Betracht ziehen":"tener en cuenta","in Betracht kommt":"entra en consideración",
"in Anspruch nehmen":"recurrir a/utilizar","nimmt in Anspruch":"recurre a",
"in Kauf nehmen":"asumir/aceptar","in Kauf genommen":"asumido",
"in Kraft treten":"entra en vigor","tritt in Kraft":"entra en vigor",
"in Kraft":"en vigor","außer Kraft":"derogado/fuera de vigor",
"in Betrieb nehmen":"poner en funcionamiento","in Betrieb genommen":"puesto en funcionamiento",
"in Betrieb":"en funcionamiento","außer Betrieb":"fuera de servicio",
"zum Einsatz kommen":"se utilizan","zum Einsatz kommt":"se utiliza",
"zur Anwendung kommen":"se aplican","zur Anwendung kommt":"se aplica",
"zum Tragen kommen":"entran en juego","zum Tragen kommt":"entra en juego",
"zur Geltung kommen":"surten efecto","macht sich bemerkbar":"se hace notar",
"spielt eine Rolle":"desempeña un papel","spielen eine Rolle":"desempeñan un papel",
"eine Rolle spielen":"desempeñar un papel","spielt keine Rolle":"no importa",
"keine Rolle spielen":"no importar","ist entscheidend":"es decisivo",
"ist maßgeblich":"es determinante","ist ausschlaggebend":"es decisivo",
"legt fest":"establece/fija","festgelegt":"establecido","festlegen":"establecer",
"trägt bei":"contribuye","tragen bei":"contribuyen","beitragen":"contribuir",
"führt zu":"conduce a","fuehren zu":"conduce a","führen dazu":"conducen a",
"resultiert aus":"resulta de","ergibt sich aus":"se deriva de",
"hängt ab von":"depende de","haengt ab von":"depende de","hängt von ab":"depende de",
"basiert auf":"se basa en","beruht auf":"se basa en",
"bezieht sich auf":"se refiere a","bezogen auf":"referido a",
"geht einher mit":"va acompañado de","einhergehen mit":"ir acompañado de",
"im Einklang mit":"en consonancia con","im einklang mit":"en consonancia con",
"in Übereinstimmung mit":"de conformidad con","in übereinstimmung mit":"de conformidad con",
"gemäß":"conforme a","gemaess":"conforme a","laut":"según",
"zufolge":"según","entsprechend":"conforme/correspondiente",
"hinsichtlich":"respecto a","bezüglich":"respecto a","bezueglich":"respecto a",
"betreffend":"relativo a","betreffs":"respecto a","angesichts":"ante/dada",
"mangels":"a falta de","trotz":"a pesar de","ungeachtet":"no obstante",
"anstelle von":"en lugar de","anstatt":"en lugar de","statt":"en lugar de",
"einschließlich":"incluido","einschliesslich":"incluido",
"ausschließlich":"exclusivamente","ausschliesslich":"exclusivamente",
"zuzüglich":"más","abzüglich":"menos","jeweils":"respectivamente",
"pro":"por","per":"por","via":"vía",
"innerhalb":"dentro de","außerhalb":"fuera de","binnen":"dentro de",
"oberhalb":"por encima de","unterhalb":"por debajo de",
"entlang":"a lo largo de","gegenüber":"frente a","gegenueber":"frente a",
"jenseits":"más allá de","diesseits":"más acá de","beiderseits":"a ambos lados",
"seitens":"por parte de","namens":"en nombre de","kraft":"en virtud de",
"anlässlich":"con motivo de","anlaesslich":"con motivo de",
"zwecks":"para/a efectos de","behufs":"a efectos de",
"in puncto":"en cuanto a","was betrifft":"en cuanto a",
"auf Kosten von":"a costa de","zu Lasten von":"a cargo de",
"zugunsten von":"en favor de","zu Gunsten von":"en favor de",
"im Auftrag von":"por encargo de","im Namen von":"en nombre de",
"im Sinne von":"en el sentido de","im sinne von":"en el sentido de",
"im Interesse":"en interés","im eigenen Interesse":"en interés propio",
"im besten Fall":"en el mejor de los casos","im schlimmsten Fall":"en el peor de los casos",
"im Idealfall":"en el caso ideal","im Normalfall":"normalmente",
"im Regelfall":"por regla general","in der Regel":"por regla general",
"in der Praxis":"en la práctica","in der Theorie":"en teoría",
"in der Tat":"de hecho","tatsächlich":"de hecho","taetsaechlich":"de hecho",
"wirklich":"realmente","eigentlich":"en realidad","grundsätzlich":"por principio",
"prinzipiell":"por principio","im Prinzip":"en principio",
"im Grunde":"en el fondo","im Grunde genommen":"en el fondo",
"genau genommen":"en sentido estricto","streng genommen":"en sentido estricto",
"kurz gesagt":"en pocas palabras","genau gesagt":"dicho con precisión",
"ehrlich gesagt":"sinceramente","offen gesagt":"francamente",
"in anderen Worten":"en otras palabras","mit anderen Worten":"en otras palabras",
"das heißt":"es decir","das heisst":"es decir",
"und so weiter":"etcétera","und so fort":"etcétera",
"unter Umständen":"en determinadas circunstancias","unter umstaenden":"en determinadas circunstancias",
"unter keinen Umständen":"bajo ninguna circunstancia","unter allen Umständen":"en todo caso",
"auf jeden Fall":"en todo caso","jedenfalls":"en todo caso",
"auf keinen Fall":"en ningún caso","keinesfalls":"en ningún caso",
"im Zweifelsfall":"en caso de duda","im zweifelsfall":"en caso de duda",
"im Notfall":"en caso de emergencia","im Ernstfall":"en caso grave",
"vor Ort":"in situ","vorort":"in situ",
"auf Anhieb":"a la primera","auf anhieb":"a la primera",
"aus dem Stegreif":"improvisando","auswendig":"de memoria",
"im Schlaf":"dormido/de carrerilla","im Vorfeld":"de antemano",
"im Nachhinein":"a posteriori","im nachhinein":"a posteriori",
"nach wie vor":"como antes/todavía","nach wie vor":"todavía",
"bis auf Weiteres":"hasta nuevo aviso","bis auf weiteres":"hasta nuevo aviso",
"bis auf Widerruf":"hasta revocación","bis auf weiteres":"hasta nuevo aviso",
"mit sofortiger Wirkung":"con efecto inmediato","mit Wirkung vom":"con efecto desde",
"rückwirkend":"con efecto retroactivo","rueckwirkend":"con efecto retroactivo",
"im Voraus":"por adelantado","im voraus":"por adelantado",
"im Nachgang":"posteriormente","nachgelagert":"posterior/aguas abajo",
"vorgelagert":"previo/aguas arriba","nachgelagert":"posterior",
" first ":" primero "," second ":" segundo ",
"auf dieser Grundlage":"sobre esta base","auf dieser Basis":"sobre esta base",
"vor diesem Hintergrund":"ante este trasfondo","vor diesem hintergrund":"ante este trasfondo",
"in diesem Zusammenhang":"en este contexto","in diesem Sinne":"en este sentido",
"in diesem Fall":"en este caso","in diesem Falle":"en este caso",
"in solchen Fällen":"en tales casos","in diesen Fällen":"en estos casos",
"unter dieser Voraussetzung":"bajo este supuesto","unter diesen Umständen":"en estas circunstancias",
"unter normalen Umständen":"en circunstancias normales",
"wenn möglich":"si es posible","wenn nötig":"si es necesario",
"wenn erforderlich":"si se requiere","falls erforderlich":"si se requiere",
"soweit möglich":"en la medida de lo posible","soweit erforderlich":"en la medida necesaria",
"so weit wie möglich":"tanto como sea posible",
"so viel wie möglich":"tanto como sea posible","so wenig wie möglich":"lo menos posible",
"so früh wie möglich":"lo antes posible","so bald wie möglich":"lo antes posible",
"zu jeder Zeit":"en todo momento","jederzeit":"en todo momento",
"zu keinem Zeitpunkt":"en ningún momento","zu keinem zeitpunkt":"en ningún momento",
"von Zeit zu Zeit":"de vez en cuando","von zeit zu zeit":"de vez en cuando",
"von Fall zu Fall":"caso por caso","von fall zu fall":"caso por caso",
"von Anfang an":"desde el principio","von anfang an":"desde el principio",
"von Grund auf":"desde cero","von grund auf":"desde cero",
"von Haus aus":"de por sí","von haus aus":"de por sí",
"von Natur aus":"por naturaleza","von natur aus":"por naturaleza",
"aus gutem Grund":"con razón","aus diesem Grund":"por este motivo",
"aus diesem grunde":"por este motivo","aus diesem Grunde":"por este motivo",
"aus Sicherheitsgründen":"por motivos de seguridad",
"aus Datenschutzgründen":"por motivos de privacidad",
"aus Kostengründen":"por motivos de coste",
"aus Zeitgründen":"por falta de tiempo","aus zeitgruenden":"por falta de tiempo",
"aus Prinzip":"por principio","aus prinzip":"por principio",
"auf Wunsch":"a petición","auf wunsch":"a petición",
"auf Anfrage":"previa solicitud","auf anfrage":"previa solicitud",
"auf Bestellung":"por encargo","auf Abruf":"a demanda/previa petición",
"auf Probe":"a prueba","auf probe":"a prueba",
"auf Raten":"a plazos","in Raten":"a plazos",
"auf Rechnung":"a cuenta/previa factura","gegen Rechnung":"contra factura",
"gegen Vorkasse":"previo pago","per Nachnahme":"contra reembolso",
"frei Haus":"franco domicilio","ab Werk":"en fábrica",
"inklusive":"incl.","inkl":"incl.","exklusive":"excl.",
"verfügbar":"disponible","verfuegbar":"disponible",
"nicht verfügbar":"no disponible","derzeit nicht verfügbar":"no disponible actualmente",
"außer Betrieb":"fuera de servicio","ausser betrieb":"fuera de servicio",
"in Betrieb":"en funcionamiento",
"sofort einsatzbereit":"listo para usar de inmediato",
"einsatzbereit":"listo para usar","betriebsbereit":"listo para operar",
"abwärtskompatibel":"retrocompatible","aufwärtskompatibel":"compatible hacia arriba",
"plattformübergreifend":"multiplataforma","plattformunabhängig":"independiente de plataforma",
"herstellerunabhängig":"independiente del fabricante","anbieterunabhängig":"independiente del proveedor",
"browserbasiert":"basado en navegador","cloudbasiert":"basado en la nube",
"dateibasiert":"basado en archivos","regelbasiert":"basado en reglas",
"ereignisgesteuert":"dirigido por eventos","datengesteuert":"dirigido por datos",
"modellgetrieben":"dirigido por modelos","testgetrieben":"dirigido por pruebas",
"benutzerfreundlich":"fácil de usar","anwenderfreundlich":"fácil de usar",
"wartungsfreundlich":"fácil de mantener","barrierefrei":"accesible/sin barreras",
"skalierbar":"escalable","erweiterbar":"ampliable","modular aufgebaut":"de estructura modular",
"lose gekoppelt":"débilmente acoplado","eng gekoppelt":"fuertemente acoplado",
"vollautomatisch":"totalmente automático","teilautomatisch":"semiautomático",
"vollautonom":"totalmente autónomo","teilautonom":"semiautónomo",
"menschüberwacht":"supervisado por humanos",
"rund um":"alrededor de","rings um":"alrededor de",
"quer durch":"a través de","mitten in":"en medio de",
"mitten im":"en medio del","inmitten":"en medio de",
"zugrunde liegend":"subyacente","zugrundeliegend":"subyacente",
"maßgeblich beteiligt":"determinante","massgeblich":"determinante",
"federführend":"coordinador/responsable","federfuehrend":"responsable",
"verantwortlich für":"responsable de","zuständig für":"competente en/responsable de",
"zustaendig fuer":"responsable de","betraut mit":"encargado de",
"beauftragt mit":"encargado de","betraut":"encargado",
"ausgestattet mit":"equipado con","versehen mit":"provisto de",
"verbunden mit":"vinculado a/asociado a","verknüpft mit":"vinculado a",
"verknuepft mit":"vinculado a","gekoppelt an":"acoplado a",
"integriert in":"integrado en","eingebettet in":"embebido en",
"eingebunden in":"integrado en","eingegliedert in":"integrado en",
"aufgeteilt in":"dividido en","unterteilt in":"subdividido en",
"gegliedert in":"estructurado en","strukturiert in":"estructurado en",
"geordnet nach":"ordenado por","sortiert nach":"ordenado por",
"gruppiert nach":"agrupado por","klassifiziert nach":"clasificado por",
"benannt nach":"llamado así por","benannt":"denominado",
"ausgerichtet auf":"orientado a","ausgerichtet an":"orientado a",
"zugeschnitten auf":"adaptado a","abgestimmt auf":"ajustado a",
"abgestimmt mit":"consensuado con","abgesprochen mit":"acordado con",
"im Einvernehmen mit":"de acuerdo con","im einvernehmen mit":"de acuerdo con",
"in Abstimmung mit":"en coordinación con","in abstimmung mit":"en coordinación con",
"in Zusammenarbeit mit":"en colaboración con","in zusammenarbeit mit":"en colaboración con",
"in Kooperation mit":"en cooperación con","gemeinsam mit":"junto con",
"zusammen mit":"junto con","neben":"junto a",
"einschließlich":"incluido","ausschließlich":"exclusivamente",
"je nach Bedarf":"según necesidad","bei Bedarf":"si es necesario",
"bei/power":"",
"auf Abruf":"a demanda","auf Knopfdruck":"pulsando un botón",
"per Mausklick":"con un clic","per Klick":"con un clic",
"finden Sie":"encontrará","finden sie":"encontrará",
"siehe":"véase","siehe auch":"véase también",
"vergleiche":"cfr.","vgl":"cfr.",
"beachten Sie":"téngase en cuenta","beachten sie":"téngase en cuenta",
"bitte beachten Sie":"téngase en cuenta, por favor",
"stellen Sie sicher":"asegúrese de","stellen sie sicher":"asegúrese de",
"achten Sie darauf":"procure","achten sie darauf":"procure",
"wählen Sie":"seleccione","waehlen sie":"seleccione",
"klicken Sie auf":"haga clic en","klicken sie auf":"haga clic en",
"geben Sie ein":"introduzca","geben sie ein":"introduzca",
"öffnen Sie":"abra","oeffnen sie":"abra","schließen Sie":"cierre",
"prüfen Sie":"verifique","pruefen sie":"verifique",
"starten Sie":"inicie","stoppen Sie":"detenga",
"warten Sie":"espere","wiederholen Sie":"repita",
"speichern Sie":"guarde","laden Sie":"cargue",
"definieren Sie":"defina","konfigurieren Sie":"configure",
"aktivieren Sie":"active","deaktivieren Sie":"desactive",
"Beispiel":"ejemplo","beispiel":"ejemplo",
"zum Beispiel":"por ejemplo","beispielsweise":"por ejemplo",
"Schema":"esquema","Ablaufdiagramm":"diagrama de flujo",
"Flussdiagramm":"diagrama de flujo","Sequenzdiagramm":"diagrama de secuencia",
"Anwendungsfall":"caso de uso","Anwendungsfälle":"casos de uso",
"Geschäftsprozess":"proceso de negocio","Geschaeftsprozess":"proceso de negocio",
"Mehrwert":"valor añadido","Alleinstellungsmerkmal":"propuesta única de venta",
"Wettbewerbsvorteil":"ventaja competitiva","Kundennutzen":"beneficio para el cliente",
"Kosten-Nutzen":"coste-beneficio","Aufwand und Ertrag":"esfuerzo y rendimiento",
"Stand der Technik":"estado de la técnica","Stand der Dinge":"estado de las cosas",
"auf dem aktuellen Stand":"al día/actualizado","nicht auf dem neuesten Stand":"desactualizado",
"von Anfang bis Ende":"de principio a fin","von A bis Z":"de la A a la Z",
"A bis Z":"de la A a la Z","Ende zu Ende":"de extremo a extremo",
"überall verfügbar":"disponible en todas partes","jederzeit abrufbar":"accesible en todo momento",
"ohne Unterbrechung":"sin interrupción","ohne Ausfallzeit":"sin inactividad",
"mit wenigen Klicks":"con pocos clics","mit wenigen Handgriffen":"con pocos gestos",
"auf Knopfdruck":"pulsando un botón","fassen wir zusammen":"resumamos",
"kommen wir zum":"pasemos al","widmen wir uns":"dediquémonos a",
"der Reihe nach":"por orden","eine nach dem anderen":"uno tras otro",
"im Einzelnen":"en detalle","in groben Zügen":"a grandes rasgos",
"anders ausgedrückt":"dicho de otro modo","mit anderen Worten":"en otras palabras",
"sozusagen":"por así decirlo","gewissermaßen":"en cierto modo",
"mehr oder weniger":"más o menos","weniger oder mehr":"más o menos",
"früher oder später":"tarde o temprano","sooner or later":"tarde o temprano",
"auf lange Sicht":"a largo plazo","auf kurze Sicht":"a corto plazo",
"auf den ersten Blick":"a primera vista","auf den zweiten Blick":"mirándolo bien",
"im Nachhinein betrachtet":"visto a posteriori","rückblickend betrachtet":"en retrospectiva",
}
WO={
"benutzer":"usuario","benutzern":"usuarios","benutzers":"del usuario","agent":"agente","agenten":"agentes",
"system":"sistema","systeme":"sistemas","systemen":"sistemas","aufgabe":"tarea","aufgaben":"tareas",
"daten":"datos","datei":"archivo","dateien":"archivos","ordner":"carpeta","fenster":"ventana",
"ansicht":"vista","ansichten":"vistas","bereich":"área","bereiche":"áreas","bereichen":"áreas",
"modul":"módulo","module":"módulos","modulen":"módulos","komponente":"componente","funktion":"función",
"merkmal":"característica","einstellung":"ajuste","konfiguration":"configuración","option":"opción",
"parameter":"parámetro","wert":"valor","werte":"valores","werten":"valores","schwelle":"umbral",
"grenze":"límite","grenzen":"límites","regel":"regla","regeln":"reglas","richtlinie":"directriz",
"vorschrift":"norma","gesetz":"ley","vertrag":"contrato","vereinbarung":"acuerdo","kunde":"cliente",
"kunden":"clientes","lieferant":"proveedor","anbieter":"proveedor","nutzer":"usuario","rolle":"rol",
"rollen":"roles","recht":"derecho","rechte":"derechos","berechtigung":"autorización","zugriff":"acceso",
"passwort":"contraseña","schlüssel":"clave","sitzung":"sesión","konto":"cuenta","profil":"perfil",
"dashboard":"panel","bericht":"informe","berichte":"informes","analyse":"análisis","statistik":"estadística",
"kennzahl":"indicador","metrik":"métrica","diagramm":"diagrama","tabelle":"tabla","tabellen":"tablas",
"liste":"lista","listen":"listas","spalte":"columna","spalten":"columnas","zeile":"fila","feld":"campo",
"formular":"formulario","schaltfläche":"botón","taste":"tecla","schalter":"interruptor","menü":"menú",
"reiter":"pestaña","symbol":"icono","meldung":"aviso","meldungen":"avisos","nachricht":"mensaje",
"hinweis":"indicación","hinweise":"indicaciones","tipp":"consejo","tipps":"consejos","beispiel":"ejemplo",
"vorlage":"plantilla","muster":"modelo","entwurf":"borrador","version":"versión","status":"estado",
"zustand":"estado","fortschritt":"avance","ergebnis":"resultado","ergebnisse":"resultados",
"ausgabe":"resultado","eingabe":"entrada","abfrage":"consulta","antwort":"respuesta","anfrage":"solicitud",
"prozess":"proceso","prozesse":"procesos","ablauf":"flujo","workflow":"flujo de trabajo","schritt":"paso",
"schritte":"pasos","schritten":"pasos","phase":"fase","phasen":"fases","stufe":"nivel","ebene":"nivel",
"säule":"pilar","baustein":"bloque","architektur":"arquitectura","infrastruktur":"infraestructura",
"netzwerk":"red","server":"servidor","dienst":"servicio","dienste":"servicios","daemon":"demonio",
"job":"trabajo","projekt":"proyecto","projekte":"proyectos","programm":"programa","anwendung":"aplicación",
"tool":"herramienta","werkzeug":"herramienta","plugin":"plugin","erweiterung":"extensión","skript":"script",
"befehl":"comando","kommando":"comando","anweisung":"instrucción","modell":"modelo","modelle":"modelos",
"team":"equipo","gremium":"comité","sitzung":"sesión","besprechung":"reunión","debatte":"debate",
"entscheidung":"decisión","entscheidungen":"decisiones","maßnahme":"medida","vorschlag":"propuesta",
"alternative":"alternativa","szenario":"escenario","risiko":"riesgo","risiken":"riesgos","chance":"oportunidad",
"gefahr":"peligro","bedrohung":"amenaza","angriff":"ataque","schutz":"protección","sicherheit":"seguridad",
"privatsphäre":"privacidad","verschlüsselung":"cifrado","backup":"respaldo","sicherung":"respaldo",
"ausfall":"fallo","störung":"incidencia","wartung":"mantenimiento","update":"actualización",
"release":"versión","patch":"parche","migration":"migración","schnittstelle":"interfaz","protokoll":"registro",
"log":"registro","logs":"registros","audit":"auditoría","kontrolle":"control","prüfung":"verificación",
"test":"prueba","tests":"pruebas","qualität":"calidad","standard":"estándar","norm":"norma",
"verfahren":"procedimiento","methode":"método","methodik":"metodología","konzept":"concepto",
"strategie":"estrategia","taktik":"táctica","ziel":"objetivo","ziele":"objetivos","zweck":"propósito",
"grund":"motivo","gründe":"motivos","ursache":"causa","wirkung":"efecto","folge":"consecuencia",
"nutzen":"beneficio","vorteil":"ventaja","nachteil":"desventaja","kosten":"costes","preis":"precio",
"budget":"presupuesto","aufwand":"esfuerzo","ertrag":"rendimiento","umsatz":"facturación","gewinn":"beneficio",
"verlust":"pérdida","marge":"margen","rechnung":"factura","angebot":"oferta","bestellung":"pedido",
"lieferung":"entrega","lager":"almacén","bestand":"existencias","artikel":"artículo","produkt":"producto",
"leistung":"prestación","durchsatz":"throughput","latenz":"latencia","last":"carga","kapazität":"capacidad",
"speicher":"memoria","arbeitsspeicher":"memoria RAM","festplatte":"disco duro","datenbank":"base de datos",
"eintrag":"entrada","transaktion":"transacción","verlauf":"historial","änderung":"cambio","ereignis":"evento",
"aktion":"acción","vorgang":"operación","erinnerung":"recordatorio","frist":"plazo","fristen":"plazos",
"termin":"cita","kalender":"calendario","zeitplan":"cronograma","planung":"planificación","betrieb":"operación",
"praxis":"práctica","theorie":"teoría","wissen":"conocimiento","information":"información","inhalt":"contenido",
"kontext":"contexto","bedeutung":"significado","definition":"definición","erklärung":"explicación",
"anleitung":"guía","handbuch":"manual","dokumentation":"documentación","leitfaden":"guía","referenz":"referencia",
"glossar":"glosario","verzeichnis":"directorio","katalog":"catálogo","sammlung":"recopilación",
"bibliothek":"biblioteca","archiv":"archivo","quelle":"fuente","quellen":"fuentes","beleg":"justificante",
"nachweis":"acreditación","anhang":"anexo","kapitel":"capítulo","abschnitt":"sección","absatz":"párrafo",
"satz":"frase","wort":"palabra","begriff":"término","begriffe":"términos","name":"nombre","titel":"título",
"einleitung":"introducción","vorwort":"prólogo","fazit":"conclusión","überblick":"resumen",
"schwerpunkt":"foco","fokus":"foco","kern":"núcleo","ausnahme":"excepción","bedingung":"condición",
"voraussetzung":"requisito","anforderung":"requisito","kriterium":"criterio","eigenschaft":"propiedad",
"variable":"variable","typ":"tipo","klasse":"clase","objekt":"objeto","abhängigkeit":"dependencia",
"anbindung":"conexión","kopplung":"acoplamiento","abstraktion":"abstracción","schicht":"capa",
"warteschlange":"cola","puffer":"búfer","cache":"caché","verbindung":"conexión","kanal":"canal",
"paket":"paquete","block":"bloque","charge":"lote","auftrag":"encargo","ticket":"tíquet","fall":"caso",
"problem":"problema","probleme":"problemas","frage":"pregunta","fragen":"preguntas","lösung":"solución",
"fehler":"error","bug":"bug","ausnahmebehandlung":"gestión de errores","wiederholung":"reintento",
"notfall":"emergencia","krise":"crisis","alarm":"alarma","warnung":"aviso","signal":"señal",
"auslöser":"desencadenante","genehmigung":"aprobación","zustimmung":"consentimiento",
"ablehnung":"rechazo","einspruch":"objeción","widerspruch":"contradicción","beschwerde":"queja",
"anspruch":"derecho","forderung":"reclamación","mahnung":"requerimiento","klage":"demanda",
"urteil":"sentencia","erlaubnis":"permiso","verbot":"prohibición","pflicht":"obligación",
"jahr":"año","jahre":"años","jahren":"años","monat":"mes","monate":"meses","woche":"semana",
"wochen":"semanas","tag":"día","tage":"días","tagen":"días","stunde":"hora","stunden":"horas",
"minute":"minuto","minuten":"minutos","sekunde":"segundo","sekunden":"segundos","zeit":"tiempo",
"zeitpunkt":"momento","zeitraum":"periodo","frist":"plazo","termin":"cita","datum":"fecha",
"mensch":"persona/humano","menschen":"personas","mitarbeiter":"empleado","kunde":"cliente",
"besucher":"visitante","teilnehmer":"participante","experte":"experto","spezialist":"especialista",
"leiter":"responsable","führung":"dirección","vorstand":"junta","abteilung":"departamento",
"firma":"empresa","unternehmen":"empresa","konzern":"grupo","betrieb":"empresa",
"branche":"sector","markt":"mercado","wettbewerb":"competencia","konkurrenz":"competencia",
"wachstum":"crecimiento","entwicklung":"desarrollo","trend":"tendencia","prognose":"previsión",
"planung":"planificación","steuerung":"dirección/control","führung":"liderazgo","leitung":"dirección",
"organisation":"organización","organigramm":"organigrama","hierarchie":"jerarquía",
"verantwortung":"responsabilidad","zuständigkeit":"competencia","kompetenz":"competencia",
"befugnis":"facultad","vollmacht":"poder/autorización","auftrag":"encargo",
"pflichtenheft":"pliego de condiciones","lastenheft":"pliego de requisitos",
"meilenstein":"hito","meilensteine":"hitos","zielsetzung":"definición de objetivos",
"kennzahlen":"indicadores","berichterstattung":"informes/reporte","controlling":"controlling",
"haushalt":"presupuesto","etat":"presupuesto","investition":"inversión","finanzierung":"financiación",
"liquidität":"liquidez","rentabilität":"rentabilidad","wirtschaftlichkeit":"rentabilidad",
"produktivität":"productividad","effizienz":"eficiencia","effektivität":"eficacia",
"qualitätssicherung":"aseguramiento de calidad","kontinuierlich":"continuo",
"zeigen":"mostrar","zeigt":"muestra","zeigen":"mostrar","gezeigt":"mostrado",
"ermöglichen":"permitir","ermöglicht":"permite","ermöglichte":"permitió",
"verhindern":"impedir","verhindert":"impide","unterstützen":"apoyar","unterstützt":"apoya",
"enthalten":"contener","enthält":"contiene","erstellen":"crear","erstellt":"crea",
"verwalten":"gestionar","verwaltet":"gestiona","speichern":"guardar","speichert":"guarda",
"senden":"enviar","sendet":"envía","empfangen":"recibir","empfängt":"recibe",
"starten":"iniciar","startet":"inicia","stoppen":"detener","überwachen":"supervisar",
"überwacht":"supervisa","prüfen":"verificar","prüft":"verifica","erkennen":"detectar",
"erkennt":"detecta","analysieren":"analizar","analysiert":"analiza","optimieren":"optimizar",
"optimiert":"optimiza","reduzieren":"reducir","reduziert":"reduce","erhöhen":"aumentar",
"erhöht":"aumenta","schützen":"proteger","schützt":"protege","sichern":"asegurar",
"synchronisieren":"sincronizar","synchronisiert":"sincroniza","protokollieren":"registrar",
"protokolliert":"registra","dokumentieren":"documentar","dokumentiert":"documenta",
"definieren":"definir","definiert":"define","konfigurieren":"configurar","konfiguriert":"configura",
"filtern":"filtrar","sortieren":"ordenar","suchen":"buscar","sucht":"busca","finden":"encontrar",
"findet":"encuentra","öffnen":"abrir","öffnet":"abre","schließen":"cerrar","schließt":"cierra",
"wechseln":"cambiar","wechselt":"cambia","wählen":"elegir","wählt":"elige","erzeugen":"generar",
"erzeugt":"genera","generieren":"generar","generiert":"genera","berechnen":"calcular",
"berechnet":"calcula","messen":"medir","misst":"mide","steuern":"controlar","automatisieren":"automatizar",
"automatisiert":"automatiza","integrieren":"integrar","integriert":"integra","verknüpfen":"vincular",
"verknüpft":"vincula","vergleichen":"comparar","vergleicht":"compara","bewerten":"evaluar",
"bewertet":"evalúa","priorisieren":"priorizar","archivieren":"archivar","archiviert":"archiva",
"löschen":"eliminar","löscht":"elimina","aktualisieren":"actualizar","aktualisiert":"actualiza",
"migrieren":"migrar","skalieren":"escalar","skaliert":"escala","begrenzen":"limitar","begrenzt":"limita",
"blockieren":"bloquear","blockiert":"bloquea","erlauben":"permitir","erlaubt":"permite",
"warnen":"advertir","warnt":"advierte","melden":"notificar","meldet":"notifica","bestätigen":"confirmar",
"bestätigt":"confirma","genehmigen":"aprobar","lehnt":"rechaza","warten":"esperar","wartet":"espera",
"pausieren":"pausar","fortsetzen":"continuar","abbrechen":"cancelar","ausführen":"ejecutar",
"führt":"conduce/ejecuta","verarbeiten":"procesar","verarbeitet":"procesa","validieren":"validar",
"validiert":"valida","testen":"probar","testet":"prueba","installieren":"instalar","installiert":"instala",
"verbinden":"conectar","verbindet":"conecta","trennen":"desconectar","authentifizieren":"autenticar",
"autorisieren":"autorizar","autorisiert":"autoriza","verschlüsseln":"cifrar","verschlüsselt":"cifra",
"bieten":"ofrecer","bietet":"ofrece","liefern":"entregar","liefert":"entrega","bereitstellen":"proporcionar",
"stellt":"plantea/proporciona","sicherstellen":"garantizar","gewährleisten":"garantizar",
"basieren":"basarse","basiert":"se basa","umfassen":"abarcar","umfasst":"abarca","decken":"cubrir",
"dienen":"servir","dient":"sirve","nutzen":"usar","nutzt":"usa","verwenden":"utilizar",
"verwendet":"utiliza","brauchen":"necesitar","braucht":"necesita","erfordern":"requerir",
"erfordert":"requiere","sparen":"ahorrar","spart":"ahorra","kosten":"costar","kostet":"cuesta",
"dauern":"durar","dauert":"dura","laufen":"ejecutarse","läuft":"se ejecuta","bleiben":"permanecer",
"bleibt":"permanece","liegen":"estar","liegt":"está","befinden":"encontrarse","erscheinen":"aparecer",
"erscheint":"aparece","wachsen":"crecer","wächst":"crece","funktionieren":"funcionar",
"funktioniert":"funciona","arbeiten":"trabajar","arbeitet":"trabaja","reagieren":"reaccionar",
"reagiert":"reacciona","antworten":"responder","antwortet":"responde","fragen":"preguntar",
"fragt":"pregunta","erklären":"explicar","erklärt":"explica","beschreiben":"describir",
"beschreibt":"describe","fassen":"resumir","fasst":"resume","betonen":"enfatizar","betont":"enfatiza",
"empfehlen":"recomendar","empfiehlt":"recomienda","vorschlagen":"proponer","schlägt":"propone",
"entscheiden":"decidir","entscheidet":"decide","planen":"planificar","plant":"planifica",
"helfen":"ayudar","hilft":"ayuda","vereinfachen":"simplificar","vereinfacht":"simplifica",
"beschleunigen":"acelerar","verbessern":"mejorar","verbessert":"mejora","ändern":"cambiar",
"ändert":"cambia","anpassen":"adaptar","angepasst":"adaptado","entfernen":"eliminar","entfernt":"elimina",
"hinzufügen":"añadir","importieren":"importar","importiert":"importa","exportieren":"exportar",
"exportiert":"exporta","teilen":"compartir","teilt":"comparte","zuweisen":"asignar","weist":"asigna",
"delegieren":"delegar","delegiert":"delega","lernen":"aprender","lernt":"aprende","erinnern":"recordar",
"vergessen":"olvidar","verstehen":"entender","versteht":"entiende","kennen":"conocer","kennt":"conoce",
"wissen":"saber","weiß":"sabe","glauben":"creer","glaubt":"cree","denken":"pensar","denkt":"piensa",
"fallen":"caer","fällt":"cae","steigen":"subir","steigt":"sube","sinken":"bajar","sinkt":"baja",
"gelten":"aplicarse","gilt":"aplica","bestehen":"existir/constar","besteht":"existe/consta",
"gehören":"pertenecer","gehört":"pertenece","entstehen":"surgir","entsteht":"surge",
"verschwinden":"desaparecer","bestehenbleiben":"mantenerse","stattfinden":"tener lugar",
"stattfindet":"tiene lugar","durchführen":"realizar","durchgeführt":"realizado","führt":"realiza",
"einführen":"introducir/implantar","eingeführt":"introducido","umsetzen":"implementar",
"umgesetzt":"implementado","umsetzen":"aplicar","abwickeln":"gestionar/tramitar","abgewickelt":"gestionado",
"übernehmen":"asumir","übernimmt":"asume","übergeben":"entregar/traspasar","übergehen":"pasar a",
"behandeln":"tratar","behandelt":"trata","bearbeiten":"tramitar/editar","bearbeitet":"tramitado",
"abarbeiten":"despachar/procesar","erledigen":"despachar/liquidar","erledigt":"despachado",
"prüfen":"comprobar","geprüft":"comprobado","freigeben":"aprobar/liberar","freigegeben":"aprobado",
"genehmigt":"aprobado","abgelehnt":"rechazado","sperren":"bloquear","gesperrt":"bloqueado",
"entsperren":"desbloquear","deaktivieren":"desactivar","deaktiviert":"desactivado",
"aktivieren":"activar","aktiviert":"activado","einschalten":"encender/activar","ausschalten":"apagar/desactivar",
"einschalten":"activar","starten":"iniciar","beenden":"finalizar","beendet":"finalizado",
"abbrechen":"cancelar","abgebrochen":"cancelado","anhalten":"detener","angehalten":"detenido",
"fortfahren":"continuar","fortgesetzt":"continuado","wiederholen":"repetir","wiederholt":"repetido",
"wiederherstellen":"restaurar","wiederhergestellt":"restaurado","zurücksetzen":"restablecer",
"zurückgesetzt":"restablecido","sichern":"respaldar","gesichert":"respaldado",
"speichern":"guardar","gespeichert":"guardado","laden":"cargar","geladen":"cargado",
"abrufen":"recuperar/consultar","abgerufen":"recuperado","aufrufen":"llamar/abrir","anzeigen":"mostrar",
"angezeigt":"mostrado","ausblenden":"ocultar","einblenden":"mostrar","darstellen":"representar",
"dargestellt":"representado","visualisieren":"visualizar","rendern":"renderizar","drucken":"imprimir",
"exportieren":"exportar","importieren":"importar","hochladen":"subir","herunterladen":"descargar",
"heruntergeladen":"descargado","synchronisieren":"sincronizar","replizieren":"replicar",
"migrieren":"migrar","migriert":"migrado","archivieren":"archivar","löschen":"eliminar",
"gelöscht":"eliminado","leeren":"vaciar","bereinigen":"depurar","bereinigt":"depurado",
"komprimieren":"comprimir","dekomprimieren":"descomprimir","verschlüsseln":"cifrar",
"entschlüsseln":"descifrar","maskieren":"enmascarar","maskiert":"enmascarado",
"hashen":"generar hash","signieren":"firmar","signiert":"firmado","verifizieren":"verificar",
"verifiziert":"verificado","validieren":"validar","authentifizieren":"autenticar",
"autorisieren":"autorizar","anmelden":"iniciar sesión","abmelden":"cerrar sesión",
"registrieren":"registrar","abonnieren":"suscribirse","kündigen":"rescindir",
"stornieren":"cancelar","buchen":"reservar/contabilizar","verbuchen":"contabilizar",
"fakturieren":"facturar","fakturiert":"facturado","mahnen":"requerir","belasten":"cargar",
"gutschreiben":"abonar","überweisen":"transferir","abbuchen":"cargar en cuenta",
"erstatten":"reembolsar","verrechnen":"compensar","abschreiben":"amortizar",
"melden":"notificar","gemeldet":"notificado","alarmieren":"alertar","benachrichtigen":"notificar",
"informieren":"informar","informiert":"informado","kommunizieren":"comunicar",
"abstimmen":"consensuar","koordinieren":"coordinar","koordiniert":"coordinado",
"delegieren":"delegar","eskalieren":"escalar","eskaliert":"escalado","priorisieren":"priorizar",
"priorisiert":"priorizado","kategorisieren":"categorizar","klassifizieren":"clasificar",
"taggen":"etiquetar","filtern":"filtrar","gefiltert":"filtrado","sortieren":"ordenar",
"sortiert":"ordenado","gruppieren":"agrupar","gruppiert":"agrupado","suchen":"buscar",
"gesucht":"buscado","gefunden":"encontrado","finden":"encontrar","entdecken":"descubrir",
"identifizieren":"identificar","identifiziert":"identificado","lokalisieren":"localizar",
"isolieren":"aislar","isoliert":"aislado","beheben":"resolver/subsanar","behoben":"resuelto",
"lösen":"resolver","gelöst":"resuelto","umgehen":"eludir/sortear","vermeiden":"evitar",
"verhindert":"impide","verhindern":"impedir","minimieren":"minimizar","minimiert":"minimizado",
"maximieren":"maximizar","optimieren":"optimizar","verbessern":"mejorar","verschlechtern":"empeorar",
"beschleunigen":"acelerar","verlangsamen":"ralentizar","stabilisieren":"estabilizar",
"skalieren":"escalar","wachsen":"crecer","schrumpfen":"reducirse","steigen":"aumentar",
"fallen":"disminuir","sinken":"descender","zunehmen":"aumentar","abnehmen":"disminuir",
"schwanken":"fluctuar","stagnieren":"estancarse","prognostizieren":"pronosticar",
"planen":"planificar","geplant":"planificado","vorbereiten":"preparar","vorbereitet":"preparado",
"organisieren":"organizar","organisiert":"organizado","strukturieren":"estructurar",
"standardisieren":"estandarizar","harmonisieren":"armonizar","zentralisieren":"centralizar",
"dezentralisieren":"descentralizar","auslagern":"externalizar","verlagern":"trasladar",
"zusammenführen":"fusionar/unificar","zusammengeführt":"fusionado","aufteilen":"dividir/repartir",
"aufgeteilt":"dividido","zusammenfassen":"resumir/agrupar","zusammengefasst":"resumido",
"gliedern":"estructurar","gegliedert":"estructurado","ordnen":"ordenar","zuordnen":"asignar",
"zugeordnet":"asignado","verknüpfen":"vincular","entkoppeln":"desacoplar","verbinden":"conectar",
"trennen":"separar","getrennt":"separado","kombinieren":"combinar","kombiniert":"combinado",
"mischen":"mezclar","mischen":"combinar","bündeln":"agrupar/paquetizar","bündeln":"concentrar",
"fokussieren":"enfocar","fokussiert":"enfocado","konzentrieren":"concentrar",
"spezialisieren":"especializar","generalisieren":"generalizar","detaillieren":"detallar",
"präzisieren":"precisar","konkretisieren":"concretar","operationalisieren":"operativizar",
"messen":"medir","gemessen":"medido","bewerten":"evaluar","bewertet":"evaluado",
"beurteilen":"juzgar/valorar","benoten":"calificar","ranken":"clasificar por rango",
"vergleichen":"comparar","verglichen":"comparado","gegenüberstellen":"contrastar",
"analysieren":"analizar","analysiert":"analizado","untersuchen":"investigar/examinar",
"untersucht":"examinado","diagnostizieren":"diagnosticar","testen":"probar","getestet":"probado",
"simulieren":"simular","simuliert":"simulado","emulieren":"emular","modellieren":"modelar",
"prognostizieren":"pronosticar","vorhersagen":"predecir","vorhergesagt":"predicho",
"schätzen":"estimar","geschätzt":"estimado","kalkulieren":"calcular","berechnen":"calcular",
"hochrechnen":"extrapolar","bilanzieren":"hacer balance","budgetieren":"presupuestar",
"entscheiden":"decidir","entschieden":"decidido","beschließen":"acordar/decidir",
"festlegen":"establecer","festgelegt":"establecido","regeln":"regular","geregelt":"regulado",
"steuern":"dirigir/controlar","gesteuert":"controlado","lenken":"dirigir","führen":"liderar",
"leiten":"dirigir","führt":"dirige","leitet":"dirige","anleiten":"instruir/guiar",
"begleiten":"acompañar","unterstützen":"apoyar","fördern":"fomentar","gefördert":"fomentado",
"fordern":"exigir","fordert":"exige","erfordern":"requerir","benötigen":"necesitar",
"benötigt":"necesita","brauchen":"necesitar","verlangen":"exigir","erwarten":"esperar",
"erwartet":"espera","hoffen":"esperar","befürchten":"temer","riskieren":"arriesgar",
"wagen":"atreverse","zögern":"dudar/vacilar","zweifeln":"dudar","hinterfragen":"cuestionar",
"reflektieren":"reflexionar","reflektiert":"reflexionado","nachdenken":"reflexionar",
"überlegen":"considerar","überlegt":"considerado","abwägen":"sopesar","abgewogen":"sopesado",
"diskutieren":"debatir","diskutiert":"debatido","debattieren":"debatir",
"argumentieren":"argumentar","behaupten":"afirmar","behauptet":"afirmado",
"bestreiten":"negar/disputar","widerlegen":"refutar","belegen":"acreditar/probar",
"belegt":"acreditado","nachweisen":"demostrar","nachgewiesen":"demostrado",
"zeigen":"mostrar","aufzeigen":"señalar","darlegen":"exponer","dargelegt":"expuesto",
"erläutern":"explicar","erläutert":"explicado","verdeutlichen":"aclarar",
"veranschaulichen":"ilustrar","illustrieren":"ilustrar","demonstrieren":"demostrar",
"präsentieren":"presentar","präsentiert":"presentado","vorstellen":"presentar",
"vorgestellt":"presentado","vorführen":"mostrar/demostrar","einführen":"introducir",
"vorführen":"exhibir","ausstellen":"exponer/emitir","zusammenfassen":"resumir",
"wiedergeben":"reproducir","zitieren":"citar","zitiert":"citado","referenzieren":"referenciar",
"verweisen":"remitir","verwiesen":"remitido","verlinken":"enlazar","verlinkt":"enlazado",
"einbetten":"embeber/incrustar","eingebettet":"embebido","hinterlegen":"depositar",
"hinterlegt":"depositado","ablegen":"archivar","abgelegt":"archivado",
"aufbewahren":"conservar/guardar","aufbewahrt":"conservado","lagern":"almacenar",
"gelagert":"almacenado","cachen":"cachear","zwischenspeichern":"almacenar temporalmente",
"puffern":"almacenar en búfer","queuen":"encolar","stapeln":"apilar",
}
ADJ={
"neu":"nuevo","neue":"nueva","neuen":"nuevos","neues":"nuevo","alt":"antiguo","aktuelle":"actual",
"wichtig":"importante","kritisch":"crítico","zentral":"central","lokal":"local","global":"global",
"intern":"interno","extern":"externo","öffentlich":"público","privat":"privado","offen":"abierto",
"aktiv":"activo","inaktiv":"inactivo","automatisch":"automático","manuell":"manual",
"dynamisch":"dinámico","statisch":"estático","flexibel":"flexible","schnell":"rápido",
"schnelle":"rápida","langsam":"lento","sofortig":"inmediato","täglich":"diario","wöchentlich":"semanal",
"monatlich":"mensual","jährlich":"anual","regelmäßig":"regular","dauerhaft":"permanente",
"temporär":"temporal","endgültig":"definitivo","stabil":"estable","robust":"robusto",
"zuverlässig":"fiable","sicher":"seguro","unsicher":"inseguro","nützlich":"útil","praktisch":"práctico",
"effizient":"eficiente","effektiv":"efectivo","skalierbar":"escalable","erweiterbar":"ampliable",
"kompatibel":"compatible","groß":"grande","große":"gran","klein":"pequeño","hoch":"alto",
"hohe":"alta","niedrig":"bajo","tief":"profundo","breit":"amplio","lang":"largo","kurz":"breve",
"kurze":"breve","schwer":"grave/difícil","leicht":"fácil/leve","einfach":"simple","komplex":"complejo",
"klar":"claro","präzise":"preciso","genau":"exacto","vollständig":"completo","teilweise":"parcial",
"gesamt":"total","komplett":"completo","lückenlos":"íntegro","direkt":"directo","explizit":"explícito",
"transparent":"transparente","verständlich":"comprensible","wahr":"verdadero","falsch":"falso",
"richtig":"correcto","korrekt":"correcto","gültig":"válido","zulässig":"admisible",
"verpflichtend":"obligatorio","optional":"opcional","verbindlich":"vinculante",
"erforderlich":"requerido","notwendig":"necesario","sinnvoll":"razonable",
"angemessen":"adecuado","veraltet":"obsoleto","modern":"moderno","klassisch":"clásico",
"verfügbar":"disponible","gesperrt":"bloqueado","freigegeben":"aprobado",
"konsistent":"consistente","parallel":"paralelo","gleichzeitig":"simultáneo",
"kontinuierlich":"continuo","periodisch":"periódico","wiederholt":"repetido",
"zufällig":"aleatorio","gezielt":"selectivo","individuell":"individual","persönlich":"personal",
"allgemein":"general","speziell":"especial","spezifisch":"específico","konkret":"concreto",
"typisch":"típico","normal":"normal","selten":"raro","häufig":"frecuente","oft":"a menudo",
"immer":"siempre","nie":"nunca","manchmal":"a veces","bereits":"ya","schon":"ya","nur":"solo",
"fast":"casi","kaum":"apenas","sehr":"muy","mehr":"más","weniger":"menos","viel":"mucho",
"wenig":"poco","auch":"también","zusätzlich":"adicional","außerdem":"además","weiterhin":"además",
"trotzdem":"sin embargo","dennoch":"sin embargo","jedoch":"sin embargo","aber":"pero",
"sondern":"sino","deshalb":"por eso","daher":"por ello","folglich":"en consecuencia",
"somit":"así pues","also":"así pues","aktuell":"actualmente","derzeit":"actualmente",
"heute":"hoy","tatsächlich":"de hecho","wirklich":"realmente","eigentlich":"en realidad",
"grundsätzlich":"por principio","möglicherweise":"posiblemente","vermutlich":"presumiblemente",
"wahrscheinlich":"probablemente","sicherlich":"ciertamente","zweifellos":"sin duda",
"mögliche":"posible","unmögliche":"imposible","machbar":"viable","notwendige":"necesaria",
"freiwillig":"voluntario","kostenlos":"gratuito","kostenpflichtig":"de pago",
"lesbar":"legible","verständlich":"comprensible","nachvollziehbar":"trazable",
"revisionssicher":"inalterable/a prueba de auditoría","manipulationssicher":"a prueba de manipulación",
"ausfallsicher":"tolerante a fallos","zukunftssicher":"a prueba de futuro",
"benutzerfreundlich":"fácil de usar","barrierefrei":"accesible","skalierbar":"escalable",
"plattformübergreifend":"multiplataforma","browserbasiert":"basado en navegador",
" separar":" separar",
}
FW={"der":"el","die":"la","das":"el","den":"el","dem":"al","des":"del","ein":"un","eine":"una",
"einem":"un","einen":"un","einer":"una","eines":"de un","einem":"un","kein":"ningún",
"keine":"ninguna","keinen":"ningún","keinem":"ningún","keiner":"ninguna","keines":"ningún",
"dieser":"este","diese":"esta","dieses":"este","diesen":"este","jedes":"cada","jeder":"cada",
"jede":"cada","jeden":"cada","alle":"todos","alles":"todo","beide":"ambos","beiden":"ambos",
"man":"se","etwas":"algo","nichts":"nada","jemand":"alguien","niemand":"nadie",
"welche":"cuál","was":"lo que","wer":"quién","wie":"cómo","wo":"dónde","wann":"cuándo",
"warum":"por qué","und":"y","oder":"o","aber":"pero","denn":"pues","sondern":"sino",
"als":"como/que","wie":"como","sowohl":"tanto","sowie":"así como","sowohl":"tanto",
"weder":"ni","noch":"ni","entweder":"o bien","in":"en","im":"en el","am":"en el","an":"en",
"auf":"en","über":"sobre","unter":"bajo","zwischen":"entre","neben":"junto a","hinter":"tras",
"vor":"ante","nach":"tras","mit":"con","ohne":"sin","für":"para","gegen":"contra","durch":"mediante",
"von":"de","vom":"del","aus":"de","bei":"en","beim":"al","zu":"a","zum":"al","zur":"a la",
"bis":"hasta","ab":"desde","seit":"desde","während":"durante","trotz":"a pesar de","statt":"en lugar de",
"wegen":"por","dank":"gracias a","laut":"según","gemäß":"conforme a","entsprechend":"conforme",
"inklusive":"incl.","zuzüglich":"más","abzüglich":"menos","innerhalb":"dentro de","außerhalb":"fuera de",
"gegenüber":"frente a","hinsichtlich":"respecto a","bezüglich":"respecto a","je":"cada",
"pro":"por","per":"por","nicht":"no","keineswegs":"de ningún modo","kaum":"apenas",
"bereits":"ya","schon":"ya","noch":"aún","schon":"ya","erst":"solo/recíen",
"nur":"solo","auch":"también","sogar":"incluso","selbst":"incluso","gerade":"justo",
"etwa":"aprox.","circa":"aprox.","rund":"alrededor de","ca":"aprox.","bzw":"resp.",
"ggf":"en su caso","d":"es decir","u":"entre otros","inkl":"incl.","exkl":"excl.",
"max":"máx.","min":"mín.","nr":"n.º","kap":"cap.","abschn":"apartado","zb":"p.ej.",
"ist":"es","sind":"son","war":"fue","waren":"fueron","sei":"sea","seien":"sean",
"sein":"ser","haben":"tener","hat":"tiene","hatte":"tenía","hatten":"tenían","habe":"tengo",
"wird":"será","werden":"serán","wurde":"fue","wurden":"fueron","worden":"sido",
"kann":"puede","können":"pueden","konnte":"pudo","könnte":"podría","muss":"debe",
"müssen":"deben","musste":"tuvo que","müsste":"debería","darf":"puede","dürfen":"pueden",
"durfte":"pudo","soll":"debe","sollen":"deben","sollte":"debería","will":"quiere",
"wollen":"quieren","wollte":"quiso","möchte":"quisiera","möchten":"quisieran",
"mag":"quiere/gusta","gibt":"hay","geben":"dar/haber","gab":"hubo","gegeben":"dado",
"geht":"va","kommen":"venir","kommt":"viene","kam":"vino","geht":"se trata",
"steht":"está/consta","stehen":"estar/constar","stand":"estuvo","liegt":"está",
"befindet":"se encuentra","handelt":"trata/actúa","betrifft":"afecta/concierne",
"mein":"mi","dein":"tu","sein":"su","ihr":"su","unser":"nuestro","euer":"vuestro",
"meine":"mi","deine":"tu","seine":"su","ihre":"su","unsere":"nuestra","eure":"vuestra",
"meinen":"mi","meinem":"mi","seinem":"su","ihrem":"su","unserem":"nuestro",
"mich":"me","dich":"te","sich":"se","uns":"nos","euch":"os","ihn":"lo","ihnen":"les",
"ich":"yo","du":"tú","er":"él","sie":"ella","es":"ello","wir":"nosotros","ihr":"vosotros",
"siem":"ellos","siepl":"ellas",
"heute":"hoy","morgen":"mañana","gestern":"ayer","jetzt":"ahora","nun":"ahora",
"bald":"pronto","sofort":"de inmediato","gleich":"enseguida","danach":"después",
"davor":"antes","dabei":"en ello","dafür":"para ello","dazu":"para ello/además",
"darauf":"sobre ello","daraus":"de ello","darin":"en ello","damit":"con ello",
"dadurch":"mediante ello","dagegen":"en cambio","daher":"por ello","darüber":"sobre ello",
"darunter":"bajo ello","daneben":"junto a ello","dahinter":"tras ello","davon":"de ello",
"hierbei":"en esto","hierzu":"al respecto","hierfür":"para esto","hiermit":"por la presente",
"hiermit":"mediante esto","wobei":"siendo que","wodurch":"por lo cual","womit":"con lo cual",
"worauf":"sobre lo cual","woraus":"de lo cual","worin":"en lo cual","worüber":"sobre lo cual",
"worunter":"bajo lo cual","wovon":"de lo cual","wozu":"para lo cual","währenddessen":"entretanto",
"unterdessen":"entretanto","inzwischen":"entretanto","mittlerweile":"entretanto",
"schließlich":"finalmente","endlich":"por fin","zuletzt":"por último","zunächst":"primero",
"zuerst":"primero","danach":"luego","anschließend":"a continuación","anschliessend":"a continuación",
"daraufhin":"acto seguido","hierauf":"a continuación","alsdann":"entonces","sodann":"luego",
"hiernach":"tras esto","nachfolgend":"a continuación","folgendermaßen":"del siguiente modo",
"beispielsweise":"por ejemplo","bedarfsweise":"según necesidad","gegebenenfalls":"en su caso",
"gegebenenfalls":"si procede","allenfalls":"a lo sumo","höchstens":"como máximo",
"mindestens":"como mínimo","wenigstens":"al menos","zumindest":"al menos","mindestens":"al menos",
"sämtlich":"todo","sämtliche":"todos","sämtlichen":"todos","gesamte":"total",
"gesamten":"total","ganze":"todo","ganzen":"todo","ganzer":"todo","halb":"medio",
"voll":"pleno/lleno","leer":"vacío","voller":"lleno de","ganze":"entero",
}
PARTS={"aktiviert":"activado","deaktiviert":"desactivado","integriert":"integrado",
"gespeichert":"guardado","gesichert":"asegurado","erstellt":"creado","definiert":"definido",
"konfiguriert":"configurado","verschlüsselt":"cifrado","archiviert":"archivado",
"gelöscht":"eliminado","aktualisiert":"actualizado","validiert":"validado","verifiziert":"verificado",
"getestet":"probado","geprüft":"verificado","optimiert":"optimizado","automatisiert":"automatizado",
"synchronisiert":"sincronizado","migriert":"migrado","freigegeben":"aprobado","genehmigt":"aprobado",
"abgelehnt":"rechazado","gesperrt":"bloqueado","gesendet":"enviado","empfangen":"recibido",
"gestartet":"iniciado","beendet":"finalizado","abgebrochen":"cancelado","reduziert":"reducido",
"erhöht":"aumentado","verbessert":"mejorado","erweitert":"ampliado","begrenzt":"limitado",
"blockiert":"bloqueado","geschützt":"protegido","überwacht":"supervisado","protokolliert":"registrado",
"dokumentiert":"documentado","analysiert":"analizado","bewertet":"evaluado","priorisiert":"priorizado",
"kategorisiert":"categorizado","klassifiziert":"clasificado","sortiert":"ordenado","gefiltert":"filtrado",
"gruppiert":"agrupado","gefunden":"encontrado","entdeckt":"descubierto","identifiziert":"identificado",
"isoliert":"aislado","gelöst":"resuelto","behoben":"resuelto","vermieden":"evitado",
"minimiert":"minimizado","gemessen":"medido","geschätzt":"estimado","berechnet":"calculado",
"geplant":"planificado","entschieden":"decidido","festgelegt":"establecido","geregelt":"regulado",
"gesteuert":"controlado","gefördert":"fomentado","reflektiert":"reflexionado","diskutiert":"debatido",
"dargelegt":"expuesto","erläutert":"explicado","präsentiert":"presentado","vorgestellt":"presentado",
"zusammengefasst":"resumido","zitiert":"citado","verlinkt":"enlazado","eingebettet":"embebido",
"hinterlegt":"depositado","abgelegt":"archivado","aufbewahrt":"conservado","gelagert":"almacenado",
"komprimiert":"comprimido","signiert":"firmado","maskiert":"enmascarado","gemeldet":"notificado",
"informiert":"informado","koordiniert":"coordinado","eskaliert":"escalado","verarbeitet":"procesado",
"angezeigt":"mostrado","dargestellt":"representado","heruntergeladen":"descargado","gedruckt":"impreso",
"exportiert":"exportado","importiert":"importado","hochgeladen":"subido","registriert":"registrado",
"fakturiert":"facturado","abgeschlossen":"concluido","erledigt":"despachado","bearbeitet":"tramitado",
"abgewickelt":"gestionado","umgesetzt":"implementado","eingeführt":"introducido","durchgeführt":"realizado",
"stattgefunden":"tenido lugar","übernommen":"asumido","übergeben":"entregado","behandelt":"tratado",
"versendet":"enviado","verteilt":"distribuido","zugestellt":"entregado","weitergeleitet":"reenviado",
"zurückgewiesen":"rechazado","angenommen":"aceptado","bestätigt":"confirmado","abgesagt":"cancelado",
"verschoben":"aplazado","abgeschlossen":"finalizado","eröffnet":"abierto","geschlossen":"cerrado",
"geöffnet":"abierto","verbunden":"conectado","getrennt":"separado","kombiniert":"combinado",
"zugeordnet":"asignado","aufgeteilt":"dividido","zusammengeführt":"fusionado","gegliedert":"estructurado",
"geordnet":"ordenado","strukturiert":"estructurado","standardisiert":"estandarizado",
"zentralisiert":"centralizado","organisiert":"organizado","vorbereitet":"preparado",
"abgeschlossen":"cerrado/concluido","erforderlich":"requerido","notwendig":"necesario",
"verfügbar":"disponible","zulässig":"admisible","verbindlich":"vinculante","betroffen":"afectado",
"beteiligt":"implicado","verantwortlich":"responsable","zuständig":"responsable",
"versehen":"provisto","ausgestattet":"equipado","verbunden":"vinculado","verknüpft":"vinculado",
"basierend":"basado","bezogen":"referido","ausgerichtet":"orientado","abgestimmt":"ajustado",
"benannt":"denominado","geordnet":"ordenado","getrennt":"separado","beschränkt":"limitado",
}
MONTHS={"januar":"enero","februar":"febrero","märz":"marzo","maerz":"marzo","april":"abril",
"mai":"mayo","juni":"junio","juli":"julio","august":"agosto","september":"septiembre",
"oktober":"octubre","november":"noviembre","dezember":"diciembre"}

SUFFIXES=["sten","ste","stem","estem","erem","eren","em","ern","er","en","es","e","n","m","s"]

def stem_lookup(w):
    if w in WORDS or w in FW or w in ADJ or w in PARTS: return w
    for suf in SUFFIXES:
        if len(w) > len(suf)+3 and w.endswith(suf):
            b = w[:-len(suf)]
            if b in WORDS or b in FW or b in ADJ or b in PARTS: return b
            if (b+"e") in WORDS: return b+"e"
            if (b+"en") in WORDS: return b+"en"
    return None

def split_compound(w):
    if len(w) < 9: return None
    for i in range(5, len(w)-4):
        a, b = w[:i], w[i:]
        if a in WORDS and b in WORDS: return (a, b)
    for i in range(5, len(w)-4):
        a, b = w[:i], w[i:]
        if stem_lookup(a) and stem_lookup(b): return (a, b)
    if "s" in w[5:-4]:
        for m in re.finditer("s", w[5:-4]):
            i = 5+m.start()
            a, b = w[:i], w[i+1:]
            if a in WORDS and b in WORDS: return (a, b)
    return None

def base_es(w):
    if w in PARTS: return PARTS[w]
    if w in WORDS: return WORDS[w]
    if w in FW: return FW[w]
    if w in ADJ: return ADJ[w]
    s = stem_lookup(w)
    if s:
        for d in (PARTS, WORDS, FW, ADJ):
            if s in d: return d[s]
    return None

WORDS = WO
WORDS_ALL = {}
WORDS_ALL.update(WO); WORDS_ALL.update(FW); WORDS_ALL.update(ADJ); WORDS_ALL.update(PARTS)

PH_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, PH.keys()), key=len, reverse=True)) + r")\b",
                   re.IGNORECASE)

def apply_case(src, dst):
    if not src or not dst: return dst
    if src.isupper() and len(src) > 1: return dst.upper()
    if src[0].isupper():
        if " " in dst: return dst[0].upper() + dst[1:]
        return dst[0].upper() + dst[1:]
    return dst

TOKEN_RE = re.compile(r"\x00\d+\x00|[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*|[0-9]+(?:[.,][0-9]+)*|\S")

def tr_word(tok):
    if re.fullmatch(r"\x00\d+\x00", tok): return tok
    if not re.search(r"[A-Za-zÄÖÜäöüß]", tok): return tok
    low = tok.lower()
    if low in ("tipp", "prompt", "schnell"):
        return {"tipp": "Consejo", "prompt": "Prompt", "schnell": "Rápido"}[low] if tok[0].isupper() else \
               {"tipp": "consejo", "prompt": "prompt", "schnell": "rápido"}[low]
    e = base_es(low)
    if e:
        if "/" in e: e = e.split("/")[0]
        return apply_case(tok, e)
    if "-" in tok and not tok.startswith("-") and not tok.endswith("-"):
        parts = tok.split("-")
        out, ok = [], True
        for p in parts:
            q = base_es(p.lower())
            if q is None: ok = False; break
            if "/" in q: q = q.split("/")[0]
            out.append(apply_case(p, q))
        if ok: return " ".join(out)
    c = split_compound(low)
    if c:
        a, b = c
        ea, eb = base_es(a), base_es(b)
        if ea and eb:
            if "/" in ea: ea = ea.split("/")[0]
            if "/" in eb: eb = eb.split("/")[0]
            return apply_case(tok, ea + " " + eb) if tok[0].islower() else apply_case(tok, ea + " " + eb)
    return tok

DATE_RE = re.compile(r"\b(\d{1,2})\.\s*(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})")
ABBR_RE = [
    (re.compile(r"\bd\.\s*h\.", re.I), "es decir"),
    (re.compile(r"\bu\.\s*a\.", re.I), "entre otros"),
    (re.compile(r"\bz\.\s*B\.", re.I), "por ejemplo"),
    (re.compile(r"\bs\.\s*o\.", re.I), "ver arriba"),
    (re.compile(r"\bs\.\s*u\.", re.I), "ver abajo"),
]

def engine_translate(text):
    lead = text[:len(text)-len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    t = text.strip()
    if not t: return text
    t = t.replace("„", "«").replace("“", "»").replace('"', "»").replace("–", "-").replace("—", "-")
    for rx, rep in ABBR_RE:
        t = rx.sub(rep, t)
    t = DATE_RE.sub(lambda m: f"{m.group(1)} de {MONTHS[m.group(2).lower()]} de {m.group(3)}", t)
    t = re.sub(r"\bAbb\.(ildung)?\s*(\d[\d\.\-]*)", r"Fig. \2", t)
    t = re.sub(r"\bAbb\.", "Fig.", t)
    masked, slots = mask(t)
    def ph_sub(m):
        src = m.group(0)
        dst = PH[src.lower()] if src.lower() in PH else PH.get(src, src)
        return apply_case(src, dst)
    masked = PH_RE.sub(ph_sub, masked)
    toks = TOKEN_RE.findall(masked)
    out = []
    i = 0
    while i < len(toks):
        o = toks[i]
        if re.fullmatch(r"\x00\d+\x00", o):
            out.append(o); i += 1; continue
        if o.lower() in ("ist", "sind") and i+1 < len(toks):
            nxt = toks[i+1].lower()
            if nxt in PARTS:
                out.append("está" if o.lower() == "ist" else "están")
                e = PARTS[nxt]
                out.append(apply_case(toks[i+1], e.split("/")[0] if "/" in e else e))
                i += 2; continue
        if o.lower() in ("wird", "werden", "wurde", "wurden"):
            rest = " ".join(x.lower() for x in toks[i+1:i+7])
            found = None
            for k in PARTS:
                if re.search(r"\b" + re.escape(k) + r"\b", rest):
                    found = k; break
            if found:
                inf = None
                for kk, vv in WORDS.items():
                    if PARTS[found].split("/")[0] == vv.split("/")[0] and kk.endswith("en"):
                        inf = vv; break
                base = (inf or PARTS[found]).split("/")[0]
                verb3 = base[:-2] + ("a" if base.endswith("ar") else "e")
                out.append("se " + verb3); i += 1; continue
            out.append({"wird": "será", "werden": "serán", "wurde": "fue", "wurden": "fueron"}[o.lower()])
            i += 1; continue
        if o.lower() in ("hat", "haben", "hast", "habe", "habt", "hatte", "hatten"):
            if i+1 < len(toks) and toks[i+1].lower() in PARTS:
                aux = {"hat": "ha", "haben": "han", "hast": "has", "habe": "he",
                       "habt": "habéis", "hatte": "había", "hatten": "habían"}[o.lower()]
                out.append(aux)
                e = PARTS[toks[i+1].lower()]
                out.append(apply_case(toks[i+1], e.split("/")[0] if "/" in e else e))
                i += 2; continue
        if o.lower() == "zu" and i+1 < len(toks):
            nl = toks[i+1].lower()
            if nl in ADJ or nl.endswith(("ig", "isch", "lich", "bar")):
                out.append("demasiado"); i += 1; continue
            if nl in WORDS or (nl.endswith("en") and base_es(nl)):
                i += 1; continue
        out.append(tr_word(o)); i += 1
    s = ""
    for j, o in enumerate(out):
        if j == 0: s = o; continue
        if re.fullmatch(r"[.,;:!?»)%\]]", o) or o.startswith("»"): s += o
        elif re.fullmatch(r"[(«]", out[j-1] if False else ""): s += o
        elif s.endswith(("(", "«", " ")) or o in ("-", "/", "&"): s += o if o in ("-", "/", "&") else o
        else: s += " " + o
    s = re.sub(r"\s+([.,;:!?%»\]])", r"\1", s)
    s = re.sub(r"([(«])\s+", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r" & ", " y ", s)
    s = re.sub(r"\by ([iíIÍ])", r"e \1", s)
    s = re.sub(r"^([a-zäöü])", lambda m: m.group(1).upper(), s.strip())
    s = unmask(s, slots)
    s = s.replace(" ,", ",").replace(" .", ".")
    return lead + s + trail

# ---------- 4. Batch-Übersetzung in den Cache (Batch-Größe ~18, nach jedem Batch speichern) ----------
CACHE_PATH = os.path.join(BASE, "data", "translation_cache_es.json")
BATCH = 18

def build_cache():
    items = json.load(open(os.path.join(BASE, "data", "unique_segments_es.json"), encoding="utf-8"))
    cache = {}
    if os.path.exists(CACHE_PATH):
        cache = json.load(open(CACHE_PATH, encoding="utf-8"))
    pending = [it["src"] for it in items if it["src"] not in cache and it["src"] not in HAND_SRC2ES]
    for src, es in HAND_SRC2ES.items():
        cache[src] = es
    print(f"Unique gesamt: {len(items)} | aus HAND: {len(HAND_SRC2ES)} | Engine-pending: {len(pending)}", flush=True)
    batch, done = [], 0
    for txt in pending:
        if len(batch) >= BATCH:
            for s_src in batch:
                cache[s_src] = engine_translate(s_src)
            done += len(batch)
            with open(CACHE_PATH, "w", encoding="utf-8") as cf:
                json.dump(cache, cf, ensure_ascii=False, indent=1)
            print(f"  Engine: {done}/{len(pending)}...", flush=True)
            batch = []
        batch.append(txt)
    if batch:
        for s_src in batch:
            cache[s_src] = engine_translate(s_src)
        done += len(batch)
        with open(CACHE_PATH, "w", encoding="utf-8") as cf:
            json.dump(cache, cf, ensure_ascii=False, indent=1)
        print(f"  Engine: {done}/{len(pending)} (fertig).", flush=True)
    return cache

# ---------- 5. Anwenden (wie translate_manual.py Zeilen 383-431) ----------
LANG_LOCALE = "es-ES"
TOC_TITLE = "Índice"
TAG = "ES"

def apply_doc(src_docx, out_docx, cache):
    doc = docx.Document(src_docx)
    body = doc._body._body
    toc_ps = {p_el for sdt in body.findall("w:sdt", NS) for p_el in sdt.findall(".//w:p", NS)}
    targets = []
    for p_el in body.iter():
        if p_el.tag.endswith("}p") and p_el not in toc_ps:
            merge_adjacent_similar_runs(p_el)
            for r_el in p_el.findall("w:r", NS):
                if r_el.find("w:drawing", NS) is not None or r_el.find("w:fldChar", NS) is not None:
                    continue
                t_els = r_el.findall("w:t", NS)
                if not t_els:
                    continue
                txt = "".join(t.text or "" for t in t_els)
                if should_skip_text(txt):
                    continue
                targets.append((r_el, t_els, txt))
    for r_el, t_els, txt in targets:
        tr = cache.get(txt, txt)
        if txt.startswith(" ") and not tr.startswith(" "):
            tr = " " + tr
        if txt.endswith(" ") and not tr.endswith(" "):
            tr = tr + " "
        t_els[0].set(qn("w:space"), "preserve")
        t_els[0].text = tr
        for extra in t_els[1:]:
            r_el.remove(extra)
    for sdt in body.findall("w:sdt", NS):
        for t in sdt.findall(".//w:t", NS):
            if t.text and t.text.strip() in ("Inhalt", "Table of Contents"):
                t.text = TOC_TITLE
    for el in body.iter():
        if el.tag.endswith("}lang"):
            el.set(qn("w:val"), LANG_LOCALE)
        elif el.tag.endswith("}t") and el.text and "(DE)" in el.text:
            el.text = el.text.replace("(DE)", f"({TAG})")
    if doc.tables:
        last_tbl = doc.tables[-1]
        trs = last_tbl._tbl.findall("w:tr", NS)
        if len(trs) > 2:
            data_trs = trs[1:]
            sorted_trs = sorted(
                data_trs,
                key=lambda tr_el: "".join(t.text or "" for t in tr_el.findall("w:tc", NS)[0].findall(".//w:t", NS)).strip().lower()
            )
            for r in data_trs:
                last_tbl._tbl.remove(r)
            for idx, r in enumerate(sorted_trs):
                for tc in r.findall("w:tc", NS):
                    tcPr = tc.find("w:tcPr", NS)
                    if tcPr is not None:
                        old = tcPr.find("w:shd", NS)
                        if old is not None:
                            tcPr.remove(old)
                        if idx % 2 == 1:
                            shd = OxmlElement("w:shd")
                            shd.set(qn("w:val"), "clear")
                            shd.set(qn("w:color"), "auto")
                            shd.set(qn("w:fill"), "F8FAFC")
                            tcPr.append(shd)
                last_tbl._tbl.append(r)
    doc.save(out_docx)
    print(f"Gespeichert: {out_docx} (Segmente: {len(targets)})", flush=True)
    return len(targets)

FILES = [
    ("docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx", "docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_ES.docx"),
    ("docs/system/ARCHON_OS_FEATURELISTE_2026.docx", "docs/system/ARCHON_OS_FEATURELISTE_2026_ES.docx"),
    ("docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.docx", "docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_ES.docx"),
]

if __name__ == "__main__":
    cache = build_cache()
    counts = {}
    for src, out in FILES:
        n = apply_doc(os.path.join(BASE, src), os.path.join(BASE, out), cache)
        counts[out] = n
    print(json.dumps(counts, ensure_ascii=False))