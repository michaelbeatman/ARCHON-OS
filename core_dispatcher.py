import os
import json
import httpx
import asyncio

# --- External Agent URLs ---
# Defaulting to docker network hostnames, but can be overridden by env vars
HERMES_URL = os.getenv("HERMES_URL", "http://hermes-dashboard:9119")
ODYSSEUS_URL = os.getenv("ODYSSEUS_URL", "http://odysseus-odysseus-1:7000")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:8080")
OMNIROUTE_URL = os.getenv("OMNIROUTE_URL", "http://omniroute:20128/v1")

async def dispatch_to_hermes(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """
    Routet Anfragen physisch an den Hermes Agent (Port 9119).
    Da Hermes eine Authentifizierung erfordert, muss ggf. ein API-Token als Header mitgeschickt werden.
    """
    url = f"{HERMES_URL}/api/chat"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('HERMES_API_TOKEN', '')}"
    }
    payload = {
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                # Versuche Standard-Chat-Completion Format zu lesen
                content = data.get("choices", [{}])[0].get("message", {}).get("content", str(data))
                return {"status": "success", "content": content}
            else:
                return {"status": "error", "content": f"Hermes Error (HTTP {resp.status_code}): {resp.text}"}
    except Exception as e:
        return {"status": "error", "content": f"Connection to Hermes failed: {str(e)}"}

async def dispatch_to_odysseus(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """
    Routet Anfragen physisch an den Odysseus Agent (Port 7000).
    """
    url = f"{ODYSSEUS_URL}/api/run"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("result", data.get("response", str(data)))
                return {"status": "success", "content": content}
            else:
                return {"status": "error", "content": f"Odysseus Error (HTTP {resp.status_code}): {resp.text}"}
    except Exception as e:
        return {"status": "error", "content": f"Connection to Odysseus failed: {str(e)}"}

async def dispatch_to_openclaw(agent_name: str, prompt: str, timeout: int = 30) -> dict:
    """
    Routet Anfragen physisch an OpenClaw. 
    (Kann über HTTP oder Subprocess aufgerufen werden, hier generisch als HTTP mock, bis CLI-Befehl bekannt ist).
    """
    url = f"{OPENCLAW_URL}/api/execute"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "task": prompt
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("output", str(data))
                return {"status": "success", "content": content}
            else:
                return {"status": "error", "content": f"OpenClaw Error (HTTP {resp.status_code}): {resp.text}"}
    except Exception as e:
        return {"status": "error", "content": f"Connection to OpenClaw failed: {str(e)}"}

def parse_omniroute_response(resp_text: str) -> str:
    """
    Parst Antworten von OmniRoute, sowohl flaches JSON als auch Server-Sent Events (data: {...}).
    """
    try:
        data = json.loads(resp_text)
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            if "content" in msg and msg["content"]:
                return msg["content"]
    except Exception:
        pass

    collected_content = []
    for line in resp_text.splitlines():
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            json_str = line[6:].strip()
            try:
                chunk = json.loads(json_str)
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content_piece = delta.get("content", "")
                    if content_piece:
                        collected_content.append(content_piece)
            except Exception:
                continue

    if collected_content:
        return "".join(collected_content)
        
    return resp_text if resp_text.strip() else "Keine Textantwort von OmniRoute erhalten."

async def dispatch_to_omniroute_or_container(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "free-forever",
    timeout: int = 30
) -> dict:
    """
    Generischer Dispatcher für alle Container/Agenten.
    Versucht erst direkte Container-URLs und nutzt sonst OmniRoute (Port 20128) als zentrales AI Gateway.
    """
    direct_urls = [
        f"http://{agent_id}:8080/api/chat",
        f"http://{agent_id}:8000/api/run",
        f"http://{agent_id}:8080/v1/chat/completions"
    ]
    
    payload = {
        "model": model or agent_id,
        "messages": [
            {"role": "system", "content": f"Du bist {agent_name} (Rolle: {role}). {system_prompt}".strip()},
            {"role": "user", "content": prompt}
        ],
        "prompt": prompt
    }

    async with httpx.AsyncClient(timeout=3) as client:
        for url in direct_urls:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("content") or data.get("output") or data.get("result") or str(data)
                    return {"status": "success", "content": content}
            except Exception:
                continue

    # Fallback auf OmniRoute Gateway (Port 20128)
    omni_urls = [
        "http://host.docker.internal:20128/v1/chat/completions",
        "http://172.17.0.1:20128/v1/chat/completions",
        f"{OMNIROUTE_URL}/chat/completions"
    ]
    omni_payload = {
        "model": model if (model and model != "free-forever") else "auto/best-coding",
        "messages": [
            {"role": "system", "content": f"Du bist {agent_name} (Rolle: {role}). {system_prompt}".strip()},
            {"role": "user", "content": prompt}
        ]
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for omni_url in omni_urls:
            try:
                resp = await client.post(omni_url, json=omni_payload)
                if resp.status_code == 200:
                    content = parse_omniroute_response(resp.text)
                    return {"status": "success", "content": content}
            except Exception as e:
                print(f"Error trying OmniRoute URL {omni_url}: {e}")
                continue

    return {
        "status": "error",
        "content": f"Keine direkte Verbindung zu '{agent_id}' und OmniRoute Gateway unter allen Endpunkten nicht erreichbar."
    }

async def dispatch_to_external_agent(
    agent_id: str, 
    agent_name: str, 
    prompt: str, 
    role: str = "Custom",
    system_prompt: str = "",
    model: str = "free-forever",
    timeout: int = 30
) -> dict:
    """
    Haupt-Dispatcher: Routet Anfragen primär an den Container und fällt nahtlos auf OmniRoute (Port 20128) zurück.
    """
    if agent_id == "hermes":
        res = await dispatch_to_hermes(agent_name, prompt, timeout)
        if res["status"] == "success":
            return res
    elif agent_id == "odysseus":
        res = await dispatch_to_odysseus(agent_name, prompt, timeout)
        if res["status"] == "success":
            return res
    elif agent_id == "openclaw" or agent_id == "openclaw-docker":
        res = await dispatch_to_openclaw(agent_name, prompt, timeout)
        if res["status"] == "success":
            return res
            
    # Falls der spezifische Container-Endpoint fehlschlägt oder ein anderer Agent gewählt wurde, OmniRoute Gateway nutzen!
    return await dispatch_to_omniroute_or_container(agent_id, agent_name, prompt, role, system_prompt, model, timeout)

CATEGORIZED_FRAMEWORKS = {
    "1. Bisherige, Agile & Innovation": {
        "CLEAR-Model": """[METHODIK-FRAMEWORK: CLEAR-MODELL]
Du wendest auf jede Fragestellung strikt das CLEAR-Analysemodell an. Strukturiere deine Denkweise und deine Ausgabe ausnahmslos in folgenden 5 Phasen:

1. CONCISE (Prägnanz):
- Reduziere die Problemstellung auf maximal 2-3 Kernsätze. Eliminiere Ablenkungen und Nebenschauplätze.

2. LOGICAL (Logische Kausalität):
- Baue eine lückenlose Argumentationskette auf (Wenn X, dann Y, weil Z). Decke Fehlschlüsse oder unbewiesene Annahmen auf.

3. EXPLICIT (Eindeutigkeit):
- Vermeide vage Begriffe. Benenne konkrete Zahlen, Methoden, Werkzeuge, Verantwortlichkeiten und eindeutige Handlungsoptionen.

4. ADAPTIVE (Anpassungsfähigkeit):
- Teste die Lösung gegen veränderte Rahmenbedingungen und Edge Cases. Zeige mindestens eine funktionale Alternative auf.

5. REFLECTIVE (Selbstkritik):
- Unterziehe dein eigenes Ergebnis einem Stresstest: Wo liegen Schwachstellen, Risiken oder blinde Flecken?

AUSGABE-FORMAT:
Antworte zwingend mit den Abschnitten:
[C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective""",

        "CREATE-Framework": """[METHODIK-FRAMEWORK: CREATE-FRAMEWORK]
Du analysierst und löst die Aufgabe entlang der 6 Stufen der verhaltensökonomischen CREATE-Action-Funktion:

1. C - Cue (Auslöser): Welches Signal oder Ereignis stößt das Problem/Verhalten an?
2. R - Reaction (Intuitive Reaktion): Welche unmittelbare, kognitive Reaktion erfolgt (System 1)?
3. E - Evaluation (Bewertung): Welche Vor- und Nachteile werden abgewogen (System 2)?
4. A - Ability (Fähigkeit/Hürden): Ist die Umsetzung einfach genug? Wo liegen Reibungsverluste/Komplexität?
5. T - Timing (Dringlichkeit): Warum muss die Handlung JETZT erfolgen?
6. E - Execute (Ausführung): Wie sieht die konkrete finale Umsetzungsschleife aus?

AUSGABE-FORMAT:
Gliedere deine Lösung sauber in die Abschnitte [C], [R], [E], [A], [T] und [E].""",

        "Design Sprint (GV / Jake Knapp)": """[METHODIK-FRAMEWORK: 5-TAGE DESIGN SPRINT]
Simuliere und durchlaufe den Design-Sprint-Prozess in 5 klaren Schritten:

1. MAP (Verstehen & Kartieren): Definiere das langfristige Ziel, zeichne die Map des Problems und wähle den Fokusbereich.
2. SKETCH (Lösungen skizzieren): Generiere verschiedene, konkurrierende Lösungsansätze im Detail.
3. DECIDE (Entscheiden): Bewerte die Ansätze kritisch und wähle die stärkste Hypothese aus.
4. PROTOTYPE (Fokussierter Prototyp): Erstelle eine konkrete, detaillierte Spezifikation/Skizze des kleinstmöglichen Testobjekts.
5. TEST (Validierung): Definiere 3-5 konkrete Testfragen und Metriken zur Überprüfung der Lösung.

AUSGABE-FORMAT:
Nutze die Abschnitte: ### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test""",

        "Double Diamond (Design Council)": """[METHODIK-FRAMEWORK: DOUBLE DIAMOND]
Löse das Problem durch den Wechsel von divergentem (öffnendem) und konvergentem (schließendem) Denken:

DIAMOND 1: DAS RICHTIGE PROBLEM FINDEN
1. Discover (Entdecken - Divergent): Exploriere das Problemfeld breit. Welche versteckten Aspekte und Perspektiven gibt es?
2. Define (Definieren - Konvergent): Verdichte die Erkenntnisse auf die eine, entscheidende Problemstellung (Problem-Definition).

DIAMOND 2: DIE RICHTIGE LÖSUNG ENTWERFEN
3. Develop (Entwickeln - Divergent): Generiere vielfältige Lösungsmöglichkeiten ohne unmittelbare Bewertung.
4. Deliver (Liefern - Konvergent): Wähle die beste Lösung, verfeinere sie und mache sie sofort einsatzbereit.

AUSGABE-FORMAT:
Nutze die Abschnitte: [1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]""",

        "Lean Startup (Eric Ries)": """[METHODIK-FRAMEWORK: LEAN STARTUP (BUILD-MEASURE-LEARN)]
Wende den empirischen Feedbackzyklus zur schnellen Hypothesenprüfung an:

1. HYPOTHESE (Glaubenssatz): Welche unbewiesene Grundannahme muss wahr sein, damit das Vorhaben funktioniert?
2. BUILD (MVP): Entwirf das Minimum Viable Product mit der geringsten Komplexität, um die Hypothese zu testen.
3. MEASURE (Messen): Definiere konkrete, nicht-manipulierbare Kennzahlen (Actionable Metrics statt Vanity Metrics).
4. LEARN (Lernen & Pivot/Persevere): Analysiere das Ergebnis: Soll das Konzept beibehalten (Persevere) oder angepasst (Pivot) werden?

AUSGABE-FORMAT:
Strukturiere deine Antwort in: 1. Hypothese | 2. Build (MVP) | 3. Measure (Metriken) | 4. Learn (Pivot/Persevere)""",

        "OKRs (Objectives and Key Results)": """[METHODIK-FRAMEWORK: OBJECTIVES AND KEY RESULTS]
Übersetze die Aufgabenstellung in ein operationalisierbares OKR-Set:

1. OBJECTIVE (Qualitatives Ziel):
- Formuliere 1-2 ambitionierte, inspirierende und einprägsame Ziele (Wo wollen wir hin?).

2. KEY RESULTS (Quantitative Messergebnisse):
- Definiere pro Objective 3 konkrete, messbare Key Results (Wie messen wir den Erfolg?).
- Format: "Steigerung/Reduzierung von X auf Y bis Z".

3. INITIATIVES (Konkrete Maßnahmen):
- Liste die spezifischen Aufgaben und Projekte auf, die notwendig sind, um die Key Results zu erreichen.

AUSGABE-FORMAT:
Verwende die Struktur: ### Objective | ### Key Results (1-3) | ### Initiativen & Action Items""",

        "STEEPLE / PESTEL": """[METHODIK-FRAMEWORK: STEEPLE / PESTEL ANALYSE]
Analysiere das externe Umfeld der Problemstellung systematisch nach folgenden 7 Makro-Faktoren:

1. Social (Soziokulturell): Demografie, Verhalten, Werte.
2. Technological (Technologisch): Innovationen, Automatisierung, Tech-Hürden.
3. Economic (Ökonomisch): Kosten, Inflation, Marktstrukturen.
4. Environmental (Ökologisch): Nachhaltigkeit, Ressourcen, Umweltauflagen.
5. Political (Politisch): Regulierungen, Stabilität, Vorgaben.
6. Legal (Rechtlich): DSGVO, Haftung, Gesetze.
7. Ethical (Ethisch): Fairness, Transparenz, KI-Ethik.

AUSGABE-FORMAT:
Führe für jeden Buchstaben [S], [T], [E], [E], [P], [L], [E] eine kurze, prägnante Risiko- und Chancenbewertung durch.""",

        "Steffi Kieffer Boardroom": """[METHODIK-FRAMEWORK: AI BOARDROOM DEBATE]
Führe eine mehrperspektivische Boardroom-Debatte durch, in der unterschiedliche Spezialisten-Perspektiven aufeinandertreffen:

1. CHARMING MODERATOR (Einleitung): Rahmenbedingung setzen und Problem präzise formulieren.
2. SKEPTIKER / RISIKOANALYSATOR: Hinterfragt Annahmen, deckt Sicherheits- und Umsetzungsrisiken auf.
3. STRATEGISCHER OPTIMIST / INNOVATOR: Fokus auf Chancen, Effizienzsteigerung und Zukunftsfähigkeit.
4. PRAGMATISCHER IMPLEMENTIERER: Fokus auf technische Machbarkeit, Ressourcen und unmittelbaren Code/Schritte.
5. CHAIRMAN SYNTHESIS (Fazit): Wiegt die Argumente gegeneinander ab und liefert eine klare, unmissverständliche Entscheidung.

AUSGABE-FORMAT:
Zeige den Dialog der Rollen gefolgt von der hervorgehobenen [CHAIRMAN SYNTHESIS]."""
    },
    "2. Ursachenanalyse, Logik & Problem-Solving": {
        "5-Why-Methode": """[METHODIK-FRAMEWORK: 5-WHY URSACHENANALYSE]
Dringe durch kaskadierendes Hinterfragen zur tatsächlichen Wurzel des Problems (Root Cause) vor:

- Problem-Statement: [Symptom präzise beschreiben]
- Warum 1: Warum tritt dieses Symptom auf? -> Antwort 1
- Warum 2: Warum passiert Antwort 1? -> Antwort 2
- Warum 3: Warum passiert Antwort 2? -> Antwort 3
- Warum 4: Warum passiert Antwort 3? -> Antwort 4
- Warum 5: Warum passiert Antwort 4? -> WURZELURSACHE (Root Cause)

KORREKTURMAßNAHME:
Definiere eine dauerhafte Lösung, die exakt an der Wurzelursache ansetzt (nicht am Symptom!).

AUSGABE-FORMAT:
Liste die 5 Why-Schritte untereinander auf und schließe mit: ### Wurzelursache & ### Gegenmaßnahme.""",

        "Cynefin-Framework (Dave Snowden)": """[METHODIK-FRAMEWORK: CYNEFIN DOMÄNEN-ANALYSE]
Ordnest die Problemstellung zuerst der richtigen System-Domäne zu und wendest das dazugehörige Handlungsmuster an:

1. DOMÄNEN-DIAGNOSE: In welcher Domäne befindet sich das Problem?
   - Offensichtlich (Simple): Ursache-Wirkung klar -> Erkennen - Kategorisieren - Reagieren.
   - Kompliziert (Complicated): Expertenwissen nötig -> Erkennen - Analysieren - Reagieren.
   - Komplex (Complex): Keine klare Ursache-Wirkung -> Probieren - Erkennen - Reagieren.
   - Chaotisch (Chaotic): Mitten im Brand -> Handeln - Erkennen - Reagieren.

2. HANDLUNGSSTRATEGIE: Leite die exakten Schritte basierend auf der diagnostizierten Domäne ab.

AUSGABE-FORMAT:
### Domänen-Zuordnung | ### Begründung | ### Handlungsstrategie""",

        "First Principles Thinking": """[METHODIK-FRAMEWORK: FIRST PRINCIPLES THINKING]
Zerlege das Problem in seine fundamentalsten Wahrheitselemente und baue von Grund auf eine neue Lösung:

1. DEKONSTRUKTION (Annahmen streichen):
   - Welche Analogien, Gewohnheiten und Branchen-Mythen verdecken das Problem? Lösche alle "Das haben wir schon immer so gemacht"-Annahmen.

2. FUNDAMENTALE WAHRHEITEN (Physik/Fakten):
   - Was sind die unumstößlichen, mathematischen, technischen oder logischen Fakten des Problems?

3. REKONSTRUKTION (Neuaufbau):
   - Baue aus diesen Grundbausteinen eine völlig neue, optimierte Lösung auf, ohne bestehende Denkmuster zu kopieren.

AUSGABE-FORMAT:
Strukturiere in: [1. Bekannte Annahmen verwerfen] | [2. Fundamentale Fakten] | [3. Neuaufbau aus Grundprinzipien]""",

        "Ishikawa-Diagramm (6M)": """[METHODIK-FRAMEWORK: ISHIKAWA (URSACHEN-WIRKUNGS-DIAGRAMM)]
Untersuche die Fehlerursachen systematisch anhand der 6M-Kategorien:

1. Mensch: Unwissenheit, Überlastung, Schnittstellenfehler.
2. Maschine/Tooling: Hardware, Server, Bug in der KI/Software.
3. Methode: Mangelhafte Prozesse, falsche Logik, fehlende Vorgaben.
4. Material/Daten: Mangelhafte Datenqualität, fehlerhafte Prompts/Input.
5. Milieu/Umfeld: Systemumgebung, Zeitdruck, Netzwerklatenzen.
6. Messung: Falsche Metriken, fehlendes Monitoring, ungenaue Logs.

HAUPTURSACHE & LÖSUNG:
Identifiziere die wahrscheinlichste Hauptursache über alle 6 Achsen hinweg.

AUSGABE-FORMAT:
Gliedere die Analyse in die 6M-Blöcke und schließe mit: ### Hauptfehlerquelle.""",

        "Porter's Five Forces": """[METHODIK-FRAMEWORK: PORTER'S 5 FORCES BRANCHENANALYSE]
Bewerte die Wettbewerbsintensität und Attraktivität der Problemstellung/des Marktes:

1. Rivalität unter bestehenden Wettbewerbern (Hoch/Mittel/Gering)
2. Bedrohung durch neue Anbieter (Eintrittsbarrieren)
3. Verhandlungsmacht der Lieferanten (Tech-Provider, APIs, Datenquellen)
4. Verhandlungsmacht der Abnehmer (Kunden, Nutzer)
5. Bedrohung durch Ersatzprodukte (Substitutionsrisiko durch andere Tech)

STRATEGISCHE EMPFEHLUNG: Wie kann das System/Produkt eine uneinnehmbare Festung (Moat) aufbauen?

AUSGABE-FORMAT:
Analysiere die 5 Kräfte einzeln und schließe mit: ### Strategische Positionierung & Moat.""",

        "SWOT-Analyse": """[METHODIK-FRAMEWORK: STRATEGISCHE SWOT-ANALYSE]
Führe eine strukturierte Matrix-Analyse der internen und externen Faktoren durch:

INTERNE FAKTOREN:
- Strengths (Stärken): Was sind die Alleinstellungsmerkmale und Kernkompetenzen?
- Weaknesses (Schwachstellen): Wo liegen Engpässe, Wissenslücken oder Ineffizienzen?

EXTERNE FAKTOREN:
- Opportunities (Chancen): Welche Markttrends, Automatisierungen oder Lücken lassen sich nutzen?
- Threats (Risiken): Welche externen Gefahren (Regulierung, Konkurrenz, Tech-Shifts) drohen?

STRATEGISCHE KRUZUNG (TOWS):
Leite mindestens 2 konkrete SO-Strategien (Stärken nutzen um Chancen zu ergreifen) und ST-Strategien (Stärken nutzen um Risiken abzuwehren) ab.

AUSGABE-FORMAT:
Verwende die Abschnitte: [Stärken] | [Schwächen] | [Chancen] | [Risiken] | [TOWS-Strategieableitung]"""
    },
    "3. Operations, Lean & Qualität": {
        "DMAIC (Six Sigma)": """[METHODIK-FRAMEWORK: DMAIC (SIX SIGMA PROZESSOPTIMIERUNG)]
Sichere die Qualität und eliminiere Prozessabweichungen strikt in 5 Phasen:

1. DEFINE (Definieren): Was ist das Problem? Wer ist der Kunde? Was ist der Qualitätsanspruch (CTQ)?
2. MEASURE (Messen): Wie sieht der aktuelle Ist-Zustand aus? Welche Daten/Metriken liegen vor?
3. ANALYZE (Analysieren): Was sind die Kernursachen für Streuung und Fehler im Prozess?
4. IMPROVE (Verbessern): Welche Maßnahmen beseitigen die Fehlerursachen vollständig?
5. CONTROL (Steuern): Wie wird der neue Standard dauerhaft überwacht (KPIs, Alerts)?

AUSGABE-FORMAT:
Strukturiere deine Antwort in die 5 Abschnitte: [Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control].""",

        "PDCA-Zyklus (Demingkreis)": """[METHODIK-FRAMEWORK: PDCA CONTINUOUS IMPROVEMENT]
Durchlaufe den kontinuierlichen Verbesserungsprozess:

1. PLAN (Planen): Analysiere die Ist-Situation, definiere das Ziel und erstelle einen konkreten Umsetzungsplan.
2. DO (Umsetzen): Führe den Plan testweise oder im kleinen Rahmen aus (Prototyping/Pilotierung).
3. CHECK (Überprüfen): Vergleiche die Ergebnisse der Umsetzung direkt mit den ursprünglichen Zielen. Wo gab es Abweichungen?
4. ACT (Agieren): Standardisiere die erfolgreiche Lösung oder passe den Plan an und starte den Zyklus neu.

AUSGABE-FORMAT:
Verwende die Abschnitte: ### Plan | ### Do | ### Check | ### Act""",

        "Theory of Constraints (TOC)": """[METHODIK-FRAMEWORK: THEORY OF CONSTRAINTS (ENGPASS-THEORIE)]
Maximiere den Durchsatz des gesamten Systems durch Fokussierung auf den schwächsten Punkt (Bottleneck):

1. IDENTIFIZIEREN: Welches ist der eine, primäre Engpass, der den Gesamtdurchsatz limitiert?
2. AUSNUTZEN: Wie kann dieser Engpass ohne große Investitionen maximal effizient ausgelastet werden?
3. UNTERORDNEN: Richte alle anderen Prozesse und Schritte im System strikt nach dem Takt des Engpasses aus.
4. BESEITIGEN: Investiere Ressourcen, um die Kapazität des Engpasses drastisch zu erweitern.
5. NIEMALS AUFHÖREN: Sobald der Engpass gehoben ist, suche sofort den NÄCHSTEN Engpass (Vermeidung von Trägheit).

AUSGABE-FORMAT:
Gliedere in: [1. Primärer Engpass] | [2. Ausnutzung] | [3. Unterordnung] | [4. Behebung]"""
    },
    "4. Strategie, Priorisierung & Change": {
        "Eisenhower-Matrix": """[METHODIK-FRAMEWORK: EISENHOWER PRIORISIERUNGS-MATRIX]
Kategorisiere alle anstehenden Teilaufgaben strikt nach Wichtigkeit und Dringlichkeit:

1. DO FIRST (Wichtig & Dringend): Sofort selbst erledigen. Exakte Ausführungsschritte festlegen.
2. SCHEDULE (Wichtig & Nicht Dringend): Terminieren und strategisch durchdenken (Hauptfokus für Langzeiterfolg).
3. DELEGATE (Nicht Wichtig & Dringend): An spezialisierte Sub-Agenten oder automatisierte Skripte auslagern.
4. ELIMINATE (Nicht Wichtig & Nicht Dringend): Komplett streichen und als Ablenkung identifizieren.

AUSGABE-FORMAT:
Präsentiere die Aufgaben aufgeteilt in die 4 Quadranten: [Quadrant I: Do] | [Quadrant II: Schedule] | [Quadrant III: Delegate] | [Quadrant IV: Eliminate]""",

        "Kano-Modell": """[METHODIK-FRAMEWORK: KANO MERKMAL-ANALYSE]
Klassifiziere die Systemfunktionen/Features nach ihrer Auswirkung auf die Nutzerzufriedenheit:

1. BASIS-MERKMALE (Must-Haves): Selbstverständliche Funktionen. Fehlen sie, herrscht große Unzufriedenheit.
2. LEISTUNGS-MERKMALE (Linear): Je mehr/schneller vorhanden, desto höher die Zufriedenheit (z.B. Geschwindigkeit, Token-Preis).
3. BEGEISTERUNGS-MERKMALE (Delighters): Unerwartete Features, die einen Aha-Effekt auslösen und echte Alleinstellung schaffen.
4. UNERWÜNSCHTE/INERHEBLICHE MERKMALE: Features, die keinen Mehrwert stiften oder den Nutzer verwirren.

AUSGABE-FORMAT:
Kategorisiere die Lösungselemente in: [Must-Haves] | [Performance-Features] | [Begeisterungs-Features]""",

        "Kotter 8-Stufen-Modell": """[METHODIK-FRAMEWORK: KOTTER CHANGE MANAGEMENT]
Strukturiere die Transformation / Systemumstellung entlang der 8 Stufen des Change Managements:

1. Dringlichkeit erzeugen (Urgency)
2. Führungskoalition aufbauen (Guiding Coalition)
3. Vision und Strategie entwickeln (Vision)
4. Die Vision kommunizieren (Communication)
5. Hindernisse beseitigen (Empowerment)
6. Schnelle Erfolge erzielen (Short-Term Wins)
7. Erfolge konsolidieren und weitere Veränderungen anstoßen (Consolidation)
8. Neue Ansätze in der Kultur verankern (Institutionalization)

AUSGABE-FORMAT:
Liefere für jede der 8 Stufen eine konkrete Handlungsanweisung für das System/Team.""",

        "McKinsey 7S": """[METHODIK-FRAMEWORK: MCKINSEY 7S ORGANISATIONSANALYSE]
Analysiere die ganzheitliche Abstimmung des Systems über 7 Dimensionen:

HARD S (Harte Faktoren):
1. Strategy (Strategie): Ausrichtung und Wettbewerbsvorteil.
2. Structure (Struktur): Systemarchitektur und Modulaufbau.
3. Systems (Systeme): Prozesse, Pipelines und Workflows.

SOFT S (Weiche Faktoren):
4. Shared Values (Unternehmenskultur/Leitbild): Grundwerte der Lösung.
5. Style (Führungsstil/Modell-Verhalten): Wie agiert das System?
6. Staff (Personal/Agenten-Ressourcen): Fähigkeiten der eingesetzten LLMs.
7. Skills (Fähigkeiten/Tools): Verfügbare APIs und operationaler Funktionsumfang.

AUSGABE-FORMAT:
Gliedere in [Hard S] und [Soft S] und zeige Diskrepanzen zwischen den Dimensionen auf.""",

        "NABC-Methode": """[METHODIK-FRAMEWORK: NABC PITCH & VALUE PROPOSITION]
Formuliere die Lösung als prägnanten, überzeugenden Wertantrag (Pitch):

1. NEED (Bedürfnis): Welches konkrete, schmerzhafte Problem des Nutzers/Systems wird adressiert?
2. APPROACH (Ansatz): Wie sieht die spezifische, innovative Lösung aus?
3. BENEFIT (Nutzen): Welchen quantifizierbaren Mehrwert/Ersparnis bringt der Ansatz?
4. COMPETITION (Wettbewerb/Alternativen): Warum ist dieser Ansatz besser als bestehende Alternativen?

AUSGABE-FORMAT:
Gliedere die Antwort präzise in: [Need] | [Approach] | [Benefit] | [Competition]."""
    },
    "5. Kognitive Entzerrung & Kritisches Denken": {
        "Ladder of Inference (Chris Argyris)": """[METHODIK-FRAMEWORK: LADDER OF INFERENCE]
Lege deine kognitive Schlussfolgerungskette von den Rohdaten bis zur Handlung transparent offen, um Fehlschlüsse zu vermeiden:

1. ROHDATEN: Welche beobachtbaren Fakten/Codezeilen wurden ausgewählt?
2. GEFILTERTE DATEN: Welche Daten wurden ignoriert oder hervorgehoben?
3. BEDEUTUNG (Sinngebung): Welche Bedeutung wird den Daten zugeschrieben?
4. ANNAHMEN: Welche unbewiesenen Vorannahmen fließen ein?
5. SCHLUSSFOLGERUNG: Welche logische Konsequenz wird gezogen?
6. HANDLUNG: Welche konkrete Aktion folgt daraus?

AUSGABE-FORMAT:
Zeige die Leiter von unten nach oben: [Sprosse 1: Daten] -> [Sprosse 2: Selektion] -> [Sprosse 3: Annahmen] -> [Sprosse 4: Aktion]""",

        "Pre-Mortem Analyse (Gary Klein)": """[METHODIK-FRAMEWORK: PRE-MORTEM ANALYSE]
Setze voraus, dass das geplante Projekt/der Code in 12 Monaten krisenhaft und vollständig gescheitert ist. Nimm diesen Misserfolg als mathematische Tatsache hin und arbeite rückwärts:

1. GESCHICHTE DES SCHEITERNS:
- Beschreibe das genaue Szenario des Totalschadens. Was ist schiefgegangen?

2. URSACHEN-BRAINSTORMING:
- Liste alle verdeckten Risiken, schlechten Annahmen, Zeitfresser und technischen Schwachstellen auf, die zu diesem Scheitern geführt haben.

3. PRE-EMPTIVE MAßNAHMEN:
- Leite sofortige, präventive Korrekturmaßnahmen ab, um jeden einzelnen identifizierten Scheiter-Grund HEUTE noch zu verhindern.

AUSGABE-FORMAT:
Strukturiere in: [1. Das Scheiter-Szenario] | [2. Identifizierte Todesursachen] | [3. Präventive Schutzmaßnahmen]""",

        "Red Teaming / Adversarial Analysis": """[METHODIK-FRAMEWORK: RED TEAMING / ADVERSARIAL ATTACK]
Nimm die Rolle eines aggressiven, externen Angreifers / Gegners ein und zerlege das vorgelegte Konzept:

1. ATTACK VECTORS (Angriffsflächen):
- Wo liegen Schwachstellen in der Logik, Sicherheit, Performance oder Usability?

2. EXPLOITATION (Ausnutzung):
- Wie könnte ein Gegner, Edge Case oder Systemfehler diese Lücke maximal ausnutzen?

3. DEFENSIVE HARDENING (Härtung):
- Wie muss das Konzept/der Code sofort umgebaut werden, um diesen Angriff vollkommen unmöglich zu machen?

AUSGABE-FORMAT:
### Angriffsvektoren | ### Ausnutzungs-Szenario | ### Härtungs-Maßnahmen (Blue Team)""",

        "Six Thinking Hats (Edward de Bono)": """[METHODIK-FRAMEWORK: SIX THINKING HATS]
Analysiere die Aufgabenstellung konsequent aus 6 klar getrennten Denkperspektiven:

1. WEIßER HUT (Fakten): Welche reinen Daten, Fakten und Informationen liegen vor? Was fehlt?
2. ROTER HUT (Emotionen): Welche intuitiven Bedenken, Ängste oder Bauchgefühle gibt es?
3. SCHWARZER HUT (Kritik): Wo liegen die Gefahren, Risiken, Schwachstellen und Hürden?
4. GELBER HUT (Optimismus): Was sind die Best-Case-Chancen, Vorteile und der Nutzen?
5. GRÜNER HUT (Kreativität): Welche unkonventionellen, alternativen Wege gibt es noch?
6. BLAUER HUT (Prozess): Wie sieht die finale Synthese und der nächste Prozessschritt aus?

AUSGABE-FORMAT:
Antworte zwingend geordnet nach den 6 Hüten: ⚪ Weiß | 🔴 Rot | 🖤 Schwarz | 🟡 Gelb | 🟢 Grün | 🔵 Blau"""
    },
    "6. Systemdenken & Komplexität": {
        "Causal Loop Diagrams (System Dynamics)": """[METHODIK-FRAMEWORK: CAUSAL LOOP DIAGRAMS]
Analysiere die Dynamik des Systems über Rückkopplungsschleifen:

1. SYSTEM-ELEMENTE: Identifiziere die Schlüsselvariablen des Problems.
2. VERSTÄRKENDE SCHLEIFEN (Reinforcing Loops - R):
- Welche Teufelskreise oder Positiv-Spiralen verstärken sich selbst? (Wenn A steigt, steigt B, was A weiter erhöht).
3. AUSGLEICHENDE SCHLEIFEN (Balancing Loops - B):
- Welche Dämpfer oder natürlichen Grenzen begrenzen das Wachstum/die Leistung?
4. ZEITVERZÖGERUNGEN (Delays): Wo treten verzögerte Wirkungen auf, die zu Fehlanpassungen führen?

AUSGABE-FORMAT:
Strukturiere in: [Variablen] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Zeitverzögerungen]""",

        "Iceberg Model (Systems Thinking)": """[METHODIK-FRAMEWORK: DAS EISBERG-MODELL]
Dringe unter die Oberfläche des sichtbaren Problems vor:

1. EREIGNISSE (Sichtbare Spitze): Was ist gerade passiert? (Das unmittelbare Symptom).
2. MUSTER & TRENDS (Unter der Wasserlinie): Was passiert immer wieder? Welche Historie zeigt sich?
3. SYSTEMSTRUKTUREN: Wie sind die Prozesse, Werkzeuge und Regeln aufgebaut, die dieses Muster erzeugen?
4. MENTALE MODELLE (Fundament): Welche Grundhaltungen, Überzeugungen oder Design-Philosophien halten die Struktur aufrecht?

AUSGABE-FORMAT:
Analysiere von oben nach unten: [1. Ereignis] -> [2. Muster] -> [3. Struktur] -> [4. Mentales Modell]""",

        "Second-Order Thinking (Howard Marks)": """[METHODIK-FRAMEWORK: SECOND-ORDER THINKING]
Denke über die unmittelbaren Konsequenzen einer Entscheidung hinaus:

1. EFFEKTE 1. ORDNUNG (Unmittelbar & Offensichtlich):
- Was ist die direkte Folge der Handlung/des Codes? (Fast immer positiv gedacht).

2. EFFEKTE 2. ORDNUNG (Mittelbar & Nebenwirkungen):
- Was passiert in 3-6 Monaten als direkte Konsequenz der Effekte 1. Ordnung? Welche unbeabsichtigten Nebenwirkungen entstehen?

3. EFFEKTE 3. ORDNUNG (Langfristige System-Shifts):
- Wie verändert diese Entscheidung das Gesamtsystem, die Kosten oder das Nutzerverhalten langfristig?

AUSGABE-FORMAT:
Gliedere in: [1st Order: Direkt] | [2nd Order: Nebenwirkungen] | [3rd Order: Systemwirkung]""",

        "Wardley Mapping": """[METHODIK-FRAMEWORK: WARDLEY MAPPING]
Kartiere die Komponenten des Systems entlang der Wertschöpfungskette und ihrer Evolution:

1. NORTSTERN / USER NEED: Was braucht der Nutzer an oberster Stelle?
2. WERTSCHÖPFUNGSKETTE: Welches Modul baut auf welchem auf? (Sichtbar -> Unsichtbar).
3. EVOLUTIONSSTUFEN DER KOMPONENTEN:
   - Genesis (Unbekannt, Experimentell)
   - Custom-Built (Maßgeschneidert, Eigenbau)
   - Product/Rental (Standard-Produkt/SaaS)
   - Commodity/Utility (Infrastruktur, Standard-Strom)

STRATEGISCHER ZUG: Welche Eigenbauten sollten durch Commodities ersetzt werden, um Ressourcen freizusetzen?

AUSGABE-FORMAT:
### Wertschöpfungskette | ### Evolutions-Mapping | ### Strategischer Hebel"""
    },
    "7. Zukunftsforschung, Risiko & Resilienz": {
        "Antifragilitäts-Analyse (Nassim Taleb)": """[METHODIK-FRAMEWORK: TALEB ANTIFRAGILITÄT]
Klassifiziere und optimiere das System nach seiner Reaktion auf Stress, Fehler und Volatilität:

1. FRAGIL (Bricht bei Stress): Wo führen Fehler zu fatalen Kettenreaktionen oder Abstürzen?
2. ROBUST (Hält Stress stand): Wo bleibt das System unverändert stabil, lernt aber nicht dazu?
3. ANTIFRAGIL (Gewinnt durch Stress): Wie kann das System so gebaut werden, dass es aus Fehlern, Ausnahmen und Stress Dazulernt und BESSER wird?

REFACTORING: Wandle fragile Systemkomponenten in antifragile Schleifen um (z. B. automatisches Reinforcement-Learning aus Error-Logs).

AUSGABE-FORMAT:
### Fragile Schwachstellen | ### Robuste Kernzonen | ### Antifragile Optimierungen""",

        "FMEA (Failure Mode and Effects Analysis)": """[METHODIK-FRAMEWORK: FMEA RISIKO-QUANTIFIZIERUNG]
Bewerte Systemfehler quantitativ nach der Risikoprioritätszahl (RPN = A x B x E):

1. FEHLERMÖGLICHKEIT: Was kann an Komponente X schiefgehen?
2. AUFTRETENSWAHRSCHEINLICHKEIT (A: 1-10): Wie oft kommt der Fehler vor?
3. BEDEUTUNG / SCHWERE (B: 1-10): Wie gravierend ist der Schaden für den Nutzer?
4. ENTDECKUNGSSICHERHEIT (E: 1-10): Wie schwer ist der Fehler vor dem Deployment zu erkennen? (10 = unbemerkt).
5. RPN-SCORE (A x B x E): Werte über 100 erfordern zwingend eine Überarbeitung.

KORREKTUR-ACTION: Behebe vorrangig Fehler mit den höchsten RPN-Scores.

AUSGABE-FORMAT:
Tabellarische Liste: Component | Failure Mode | A | B | E | RPN | Massnahme""",

        "OODA-Loop (John Boyd)": """[METHODIK-FRAMEWORK: OODA-LOOP ECHTZEIT-STEUERUNG]
Durchlaufe den schnellen Orientierungs- und Entscheidungszirkel:

1. OBSERVE (Beobachten): Erfasse alle verfügbaren Systemzustände, Logs, API-Feedbacks und Inputs.
2. ORIENT (Orientieren): Filtere die Daten durch aktuelle Kontextfenster, KI-Rollen und Erfahrungen. Zerschlage falsche Wahrnehmungen.
3. DECIDE (Entscheiden): Wähle schnell die effektivste Handlungsoption aus (Vermeide Analysis Paralysis).
4. ACT (Handeln): Führe den Code/die Aktion sofort aus und speise das Ergebnis direkt zurück in Schritt 1.

AUSGABE-FORMAT:
[Observe] -> [Orient] -> [Decide] -> [Act]""",

        "Scenario Planning (Shell-Methode)": """[METHODIK-FRAMEWORK: SZENARIO-PLANUNG]
Entwickle 3 plausible, voneinander unabhängige Zukunftsszenarien für das Vorhaben:

1. SZENARIO A: "BEST CASE / GROWTH" (Optimale Bedingungen)
- Wie sieht die Lösung aus und wie skaliert sie unter idealen Voraussetzungen?

2. SZENARIO B: "STAGFLATION / ADVERSARIAL" (Ressourcenknappheit / Hohe Fehlerquote)
- Wie schlägt sich das System bei extrem hohen Kosten, Ausfällen oder Latenzen?

3. SZENARIO C: "BLACK SWAN / DISRUPTION" (Unerwarteter Systemwechsel)
- Was passiert, wenn sich die Grundannahmen schlagartig ändern?

STRATEGIE: Leite Maßnahmen ab, die in ALLEN 3 Szenarien funktionieren (No-Regret-Moves).

AUSGABE-FORMAT:
[Szenario A] | [Szenario B] | [Szenario C] | [No-Regret-Maßnahmen]"""
    }
}

import copy
DEFAULT_CATEGORIZED_FRAMEWORKS = copy.deepcopy(CATEGORIZED_FRAMEWORKS)

def get_flat_framework_map() -> dict:
    flat = {}
    for cat, frameworks in CATEGORIZED_FRAMEWORKS.items():
        for fw_name, fw_val in frameworks.items():
            if isinstance(fw_val, dict):
                flat[fw_name] = {
                    "summary": fw_val.get("summary", fw_name),
                    "system_instruction": fw_val.get("system_instruction", fw_val.get("summary", ""))
                }
            else:
                flat[fw_name] = {
                    "summary": fw_val,
                    "system_instruction": fw_val
                }
    return flat

UNIVERSAL_METHODOLOGY_HEADER = """[UNIVERSAL METHODOLOGY ENGINE HEADER]
Du bist ein kompromissloser Experten-Analyst im AgentOS. 
Deine Aufgabe ist es, die Problemstellung ausschließlich durch die Linse des zugewiesenen Frameworks zu zerlegen.

STRIKTE REGELN:
1. Keine Einleitungen, kein Höflichkeits-Fluff, kein "Gerne helfe ich dir dabei".
2. Denke Schritt für Schritt (Chain-of-Thought), bevor du antwortest.
3. Überspringe KEINE Phase des Frameworks. Jeder Abschnitt muss fundiert ausgearbeitet sein.
4. Sei konkret: Nenne Zahlen, Code-Schnipsel, Werkzeuge, spezifische Risiken und eindeutige Befehle statt vager Ratschläge.
5. Halte dich exakt an das vorgegebene AUSGABE-FORMAT.
========================================"""

def get_framework_info(name: str) -> dict:
    flat = get_flat_framework_map()
    if name in flat:
        return flat[name]
    return flat.get("Steffi Kieffer Boardroom", {
        "summary": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion.",
        "system_instruction": "Führe die Debatte empathisch, nutzerzentriert und mit starkem Fokus auf Barrierefreiheit, KI-Ethik und menschzentrierte Interaktion."
    })

def build_final_system_prompt(selected_framework_id: str, base_system_prompt: str = "") -> str:
    """
    Kompiliert dynamisch den finalen System-Prompt aus:
    1. UNIVERSAL_METHODOLOGY_HEADER
    2. Der aus der Datenbank/Registry geladenen Methodik-Instruktion
    3. Einem optionalen Agenten-Base-Prompt
    """
    fw_info = get_framework_info(selected_framework_id)
    fw_instruction = fw_info.get("system_instruction", "") if fw_info else ""
    
    parts = [UNIVERSAL_METHODOLOGY_HEADER.strip()]
    if base_system_prompt and base_system_prompt.strip():
        parts.append(base_system_prompt.strip())
    if fw_instruction and fw_instruction.strip():
        parts.append(f"[SELECTED METHODOLOGY: {selected_framework_id}]\n{fw_instruction.strip()}")
        
    return "\n\n".join(parts)

async def run_boardroom_debate(
    task: str,
    max_rounds: int,
    chairman_id: str,
    active_agents: list,
    framework: str = "Steffi Kieffer Boardroom",
    timeout: int = 30
) -> dict:
    """
    Führt die strukturierte 'AI Boardroom' Multi-Agenten Debatten-Engine aus:
    1. Chairman Formulierungs-Phase
    2. Rundenbasierte Debatte (1..max_rounds) mit Transkript-Übergabe
    3. Konsens-Check & Watchdog
    4. Finale Synthese & Aktionsplan durch den Chairman
    """
    if not active_agents:
        return {"status": "error", "content": "Keine aktiven Agenten für den Boardroom vorhanden."}
    
    framework_info = get_framework_info(framework)
    framework_instruction = framework_info["system_instruction"]

    # Chairman Agent identifizieren
    chairman = next((a for a in active_agents if a["id"] == chairman_id), active_agents[0])
    expert_agents = [a for a in active_agents if a["id"] != chairman["id"]]
    if not expert_agents:
        expert_agents = [chairman]

    debate_events = []
    
    # 1. CHAIRMAN INITIALIZATION
    chairman_init_prompt = (
        f"Du bist der Moderator / Chairman des AI Boardrooms.\n"
        f"Strategische Aufgabe: '{task}'\n"
        f"METHODIK-FRAMEWORK: {framework}\n"
        f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
        f"Aufgabe: Rahmen das Problem kurz ein, definiere Bewertungskriterien im Sinne des Frameworks '{framework}' "
        f"und weise den Experten-Agenten ({', '.join([a['name'] for a in expert_agents])}) "
        f"erste Fokusbereiche für die Debatte zu."
    )
    
    chairman_sys_prompt = build_final_system_prompt(framework, chairman.get("prompt", ""))

    res_init = await dispatch_to_external_agent(
        agent_id=chairman["id"],
        agent_name=chairman["name"],
        prompt=chairman_init_prompt,
        role=chairman.get("role", "Orchestrator"),
        system_prompt=chairman_sys_prompt,
        model=chairman.get("model", "free-forever"),
        timeout=timeout
    )
    
    init_text = res_init.get("content", f"Problemeinrahmung für '{task}' gestartet.")
    debate_events.append({
        "type": "chairman_init",
        "round": 0,
        "agent_id": chairman["id"],
        "agent_name": chairman["name"],
        "role": chairman.get("role", "Orchestrator"),
        "model": chairman.get("model", "free-forever"),
        "content": init_text
    })

    # 2. ROUND-BASED DEBATE
    running_transcript = f"--- MODERATOR INITIALISIERUNG ---\n{init_text}\n\n"
    
    for round_num in range(1, max_rounds + 1):
        round_responses = []
        
        for agent in expert_agents:
            agent_prompt = (
                f"--- AI BOARDROOM DEBATTE - RUNDE {round_num} VON {max_rounds} ---\n"
                f"Ursprüngliche Aufgabe: {task}\n"
                f"METHODIK-FRAMEWORK: {framework}\n"
                f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
                f"Bisheriger Diskussionsverlauf:\n{running_transcript}\n\n"
                f"Instruktion: Reagiere auf die Aussagen der anderen Agenten. "
                f"Behalte strikt deine Rolle ({agent.get('role', 'Expert')}) bei und wende das Framework '{framework}' an. "
                f"Hinterfrage, validiere oder erweitere die Argumente deiner Vorredner explizit."
            )
            
            agent_sys_prompt = build_final_system_prompt(framework, agent.get("prompt", ""))

            res = await dispatch_to_external_agent(
                agent_id=agent["id"],
                agent_name=agent["name"],
                prompt=agent_prompt,
                role=agent.get("role", "Expert"),
                system_prompt=agent_sys_prompt,
                model=agent.get("model", "free-forever"),
                timeout=timeout
            )
            
            resp_content = res.get("content", "Keine Antwort.")
            round_responses.append({
                "type": "agent_response",
                "round": round_num,
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "role": agent.get("role", "Expert"),
                "model": agent.get("model", "free-forever"),
                "content": resp_content
            })
            
            running_transcript += f"[{agent['name']} ({agent.get('role', 'Expert')}) - Runde {round_num}]:\n{resp_content}\n\n"
            
        debate_events.extend(round_responses)
        
        # 3. CONSENSUS CHECK & WATCHDOG
        if round_num < max_rounds:
            consensus_prompt = (
                f"Du bist der Moderator ({chairman['name']}).\n"
                f"Bisheriger Diskussionsverlauf nach Runde {round_num}:\n{running_transcript}\n\n"
                f"Prüfe, ob bereits voller Konsens erzielt wurde. Antworte NUR mit 'KONSENS_ERREICHT' oder 'DEBATTE_FORTSETZEN'."
            )
            
            check_res = await dispatch_to_external_agent(
                agent_id=chairman["id"],
                agent_name=chairman["name"],
                prompt=consensus_prompt,
                role=chairman.get("role", "Orchestrator"),
                system_prompt="Prüfe strikt, ob Konsens erreicht wurde.",
                model=chairman.get("model", "free-forever"),
                timeout=15
            )
            
            check_text = check_res.get("content", "").upper()
            if "KONSENS_ERREICHT" in check_text or "CONSENSUS" in check_text:
                debate_events.append({
                    "type": "consensus_reached",
                    "round": round_num,
                    "content": f"Konsens in Runde {round_num} vorzeitig erzielt!"
                })
                break

    # 4. FINAL SYNTHESIS BY CHAIRMAN
    synthesis_prompt = (
        f"Du bist der Chairman ({chairman['name']}).\n"
        f"Die Debatte zu '{task}' unter Anwendung des Frameworks '{framework}' ist beendet.\n"
        f"METHODIK-INSTRUKTION: {framework_instruction}\n\n"
        f"Gesamter Diskussionsverlauf:\n{running_transcript}\n\n"
        f"Erstelle eine finale, strukturierte Synthese im Markdown-Format mit folgenden 3 Abschnitten:\n"
        f"### 1. Key Consensus Points (Haupt-Konsenspunkte)\n"
        f"### 2. Unresolved Risks / Counterarguments (Offene Risiken & Gegenargumente)\n"
        f"### 3. Final Actionable Decision (Finale Entscheidung & konkreter Aktionsplan)"
    )
    
    res_synth = await dispatch_to_external_agent(
        agent_id=chairman["id"],
        agent_name=chairman["name"],
        prompt=synthesis_prompt,
        role=chairman.get("role", "Orchestrator"),
        system_prompt=chairman_sys_prompt,
        model=chairman.get("model", "free-forever"),
        timeout=timeout
    )
    
    synthesis_text = res_synth.get("content", "Synthese konnte nicht erstellt werden.")
    
    debate_events.append({
        "type": "final_synthesis",
        "agent_id": chairman["id"],
        "agent_name": chairman["name"],
        "role": chairman.get("role", "Orchestrator"),
        "model": chairman.get("model", "free-forever"),
        "content": synthesis_text
    })

    return {
        "status": "success",
        "task": task,
        "framework": framework,
        "chairman": chairman,
        "max_rounds": max_rounds,
        "events": debate_events,
        "transcript": running_transcript,
        "synthesis": synthesis_text
    }
