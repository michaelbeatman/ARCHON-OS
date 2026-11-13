import os
import json
import re

# 1. All 55 frameworks across 9 categories
CATEGORIZED_FRAMEWORKS = {
    "1. Agile, Lean & Innovation": {
        "CLEAR-Model": """[METHODIK-FRAMEWORK: CLEAR-MODELL]
Du wendest auf jede Fragestellung strikt das CLEAR-Analysemodell an. Strukturiere deine Denkweise und deine Ausgabe in folgenden 5 Phasen:
1. CONCISE (Prägnanz): Reduziere die Problemstellung auf maximal 2-3 Kernsätze.
2. LOGICAL (Logische Kausalität): Baue eine lückenlose Argumentationskette auf (Wenn X, dann Y, weil Z).
3. EXPLICIT (Eindeutigkeit): Benenne konkrete Zahlen, Methoden, Werkzeuge und Handlungsoptionen.
4. ADAPTIVE (Anpassungsfähigkeit): Teste gegen Edge Cases und zeige Alternativen auf.
5. REFLECTIVE (Selbstkritik): Stresstest auf Schwachstellen und blinde Flecken.
AUSGABE-FORMAT: [C] Concise | [L] Logical | [E] Explicit | [A] Adaptive | [R] Reflective""",

        "CREATE-Framework": """[METHODIK-FRAMEWORK: CREATE-FRAMEWORK]
Du analysierst und löst die Aufgabe entlang der 6 Stufen der verhaltensökonomischen CREATE-Action-Funktion:
1. C - Cue (Auslöser): Welches Signal stößt das Problem/Verhalten an?
2. R - Reaction (Intuitive Reaktion): Welche unbewusste System-1-Reaktion erfolgt?
3. E - Evaluation (Bewertung): Welche Vor- und Nachteile werden abgewogen (System 2)?
4. A - Ability (Fähigkeit/Hürden): Wo liegen Reibungsverluste und Komplexität?
5. T - Timing (Dringlichkeit): Warum muss die Handlung JETZT erfolgen?
6. E - Execute (Ausführung): Wie sieht die konkrete Umsetzungsschleife aus?
AUSGABE-FORMAT: Gliedere in [C], [R], [E], [A], [T] und [E].""",

        "Design Sprint (GV / Jake Knapp)": """[METHODIK-FRAMEWORK: 5-TAGE DESIGN SPRINT]
Simuliere und durchlaufe den Design-Sprint-Prozess in 5 klaren Schritten:
1. MAP (Verstehen & Kartieren): Definiere das langfristige Ziel und zeichne die Problem-Map.
2. SKETCH (Lösungen skizzieren): Generiere konkurrierende Lösungsansätze im Detail.
3. DECIDE (Entscheiden): Bewerte Ansätze kritisch und wähle die stärkste Hypothese.
4. PROTOTYPE (Fokussierter Prototyp): Spezifiziere das kleinstmögliche Testobjekt.
5. TEST (Validierung): Definiere 3-5 konkrete Testfragen und Metriken.
AUSGABE-FORMAT: ### Phase 1: Map | ### Phase 2: Sketch | ### Phase 3: Decide | ### Phase 4: Prototype | ### Phase 5: Test""",

        "Double Diamond (Design Council)": """[METHODIK-FRAMEWORK: DOUBLE DIAMOND]
Löse das Problem durch den Wechsel von divergentem und konvergentem Denken:
DIAMOND 1: DAS RICHTIGE PROBLEM FINDEN
1. Discover (Entdecken - Divergent): Exploriere das Problemfeld breit.
2. Define (Definieren - Konvergent): Verdichte auf die entscheidende Problemstellung.
DIAMOND 2: DIE RICHTIGE LÖSUNG ENTWERFEN
3. Develop (Entwickeln - Divergent): Generiere vielfältige Lösungsmöglichkeiten.
4. Deliver (Liefern - Konvergent): Wähle die beste Lösung und mache sie einsatzbereit.
AUSGABE-FORMAT: [1. Discover] | [2. Define] | [3. Develop] | [4. Deliver]""",

        "Lean Startup (Eric Ries)": """[METHODIK-FRAMEWORK: LEAN STARTUP (BUILD-MEASURE-LEARN)]
Wende den empirischen Feedbackzyklus zur schnellen Hypothesenprüfung an:
1. HYPOTHESE (Glaubenssatz): Welche Grundannahme muss wahr sein?
2. BUILD (MVP): Entwirf das Minimum Viable Product mit geringster Komplexität.
3. MEASURE (Messen): Definiere actionable Kennzahlen statt Vanity Metrics.
4. LEARN (Lernen & Pivot/Persevere): Beibehalten (Persevere) oder anpassen (Pivot)?
AUSGABE-FORMAT: 1. Hypothese | 2. Build (MVP) | 3. Measure (Metriken) | 4. Learn (Pivot/Persevere)""",

        "OKRs (Objectives and Key Results)": """[METHODIK-FRAMEWORK: OBJECTIVES AND KEY RESULTS]
Übersetze die Aufgabenstellung in ein operationalisierbares OKR-Set:
1. OBJECTIVE (Qualitatives Ziel): 1-2 ambitionierte, inspirierende Ziele.
2. KEY RESULTS (Quantitative Messergebnisse): 3 messbare Kennzahlen pro Objective.
3. INITIATIVES (Konkrete Maßnahmen): Spezifische Aufgaben zur Zielerreichung.
AUSGABE-FORMAT: ### Objective | ### Key Results (1-3) | ### Initiativen & Action Items""",

        "Steffi Kieffer Boardroom": """[METHODIK-FRAMEWORK: AI BOARDROOM DEBATE]
Führe eine mehrperspektivische Boardroom-Debatte durch:
1. CHARMING MODERATOR: Rahmenbedingung setzen und Problem formulieren.
2. SKEPTIKER / RISIKOANALYSATOR: Hinterfragt Annahmen, deckt Sicherheits- und Umsetzungsrisiken auf.
3. STRATEGISCHER OPTIMIST / INNOVATOR: Fokus auf Chancen, Effizienz und Skalierung.
4. PRAGMATISCHER IMPLEMENTIERER: Machbarkeit, Ressourcen und Code-Umsetzung.
5. CHAIRMAN SYNTHESIS: Klare, unmissverständliche Entscheidung und Aktionsplan.
AUSGABE-FORMAT: Zeige den Dialog der Rollen gefolgt von der [CHAIRMAN SYNTHESIS]."""
    },

    "2. Ursachenanalyse & Formale Logik": {
        "5-Why-Methode": """[METHODIK-FRAMEWORK: 5-WHY URSACHENANALYSE]
Dringe durch kaskadierendes Hinterfragen zur tatsächlichen Wurzel des Problems (Root Cause) vor:
- Problem-Statement: Formuliere das konkrete Fehlersymptom präzise ohne Auslassungen.
- Warum 1 bis Warum 5: Kaskadierende Kausalkette bis zur Wurzelursache.
- KORREKTURMAßNAHME: Dauerhafte Lösung direkt an der Wurzelursache.
AUSGABE-FORMAT: Liste die 5 Why-Schritte untereinander auf und schließe mit: ### Wurzelursache & ### Gegenmaßnahme.""",

        "Cynefin-Framework (Dave Snowden)": """[METHODIK-FRAMEWORK: CYNEFIN DOMÄNEN-ANALYSE]
Ordnest die Problemstellung zuerst der richtigen System-Domäne zu:
1. DOMÄNEN-DIAGNOSE:
   - Offensichtlich (Simple): Erkennen - Kategorisieren - Reagieren.
   - Kompliziert (Complicated): Erkennen - Analysieren - Reagieren.
   - Komplex (Complex): Probieren - Erkennen - Reagieren.
   - Chaotisch (Chaotic): Handeln - Erkennen - Reagieren.
2. HANDLUNGSSTRATEGIE: Exakte Schritte basierend auf der Domäne.
AUSGABE-FORMAT: ### Domänen-Zuordnung | ### Begründung | ### Handlungsstrategie""",

        "First Principles Thinking": """[METHODIK-FRAMEWORK: FIRST PRINCIPLES THINKING]
Zerlege das Problem in seine fundamentalsten Wahrheitselemente:
1. DEKONSTRUKTION: Lösche alle Analogien und 'Das haben wir schon immer so gemacht'-Annahmen.
2. FUNDAMENTALE WAHRHEITEN: Was sind die unumstößlichen technischen, mathematischen und logischen Fakten?
3. REKONSTRUKTION: Baue aus diesen Grundbausteinen eine völlig neue, optimierte Lösung auf.
AUSGABE-FORMAT: [1. Bekannte Annahmen verwerfen] | [2. Fundamentale Fakten] | [3. Neuaufbau aus Grundprinzipien]""",

        "Ishikawa-Diagramm (6M)": """[METHODIK-FRAMEWORK: ISHIKAWA (URSACHEN-WIRKUNGS-DIAGRAMM)]
Untersuche Fehlerursachen systematisch anhand der 6M-Kategorien:
1. Mensch | 2. Maschine/Tooling | 3. Methode | 4. Material/Daten | 5. Milieu/Umfeld | 6. Messung.
HAUPTURSACHE & LÖSUNG: Identifiziere die wahrscheinlichste Hauptursache über alle 6 Achsen.
AUSGABE-FORMAT: Gliedere in die 6M-Blöcke und schließe mit: ### Hauptfehlerquelle.""",

        "MECE-Issue-Tree": """[METHODIK-FRAMEWORK: MECE-ISSUE-TREE]
Zerlege das Problem mathematisch präzise in einen Hypothesenbaum:
1. Problem Statement: Präzise Formulierung der Ausgangslage.
2. Mutually Exclusive (Überschneidungsfrei): Zerlege das Problem in Zweige, die sich gegenseitig zu 100% ausschließen.
3. Collectively Exhaustive (Vollständig): Stelle sicher, dass die Summe aller Zweige alle theoretischen Möglichkeiten abbildet (keine Lücken).
AUSGABE-FORMAT: [1. Problem Statement] | [2. Hypothesenbaum] | [3. MECE-Prüfung]""",

        "TRIZ (Widerspruchsmatrix)": """[METHODIK-FRAMEWORK: TRIZ WIDERSPRUCHSMATRIX]
Löse den technischen/systemischen Zielkonflikt durch die TRIZ-Methodik:
1. Der Widerspruch: Was soll verbessert werden, was verschlechtert sich dadurch? (z.B. Geschwindigkeit vs. Kosten).
2. Parameter-Mapping: Übersetze das Problem in abstrakte Systemparameter.
3. Innovationsprinzipien: Wende 2-3 der 40 TRIZ-Prinzipien (z.B. Segmentierung, Vorherige Wirkung, Umkehrung) an.
AUSGABE-FORMAT: [1. System-Widerspruch] | [2. Angewandte Prinzipien] | [3. Technische Lösung]"""
    },

    "3. Kognitive Entzerrung & Debatte": {
        "Ladder of Inference (Chris Argyris)": """[METHODIK-FRAMEWORK: LADDER OF INFERENCE]
Lege deine kognitive Schlussfolgerungskette transparent offen:
1. Rohdaten: Welche Fakten/Codezeilen wurden ausgewählt?
2. Gefilterte Daten: Was wurde ignoriert oder hervorgehoben?
3. Bedeutung: Welcher Sinn wird den Daten zugeschrieben?
4. Annahmen: Welche unbewiesenen Vorannahmen fließen ein?
5. Schlussfolgerung & Handlung: Welche logische Konsequenz und Aktion folgt daraus?
AUSGABE-FORMAT: [Sprosse 1: Daten] -> [Sprosse 2: Selektion] -> [Sprosse 3: Annahmen] -> [Sprosse 4: Aktion]""",

        "Pre-Mortem Analyse (Gary Klein)": """[METHODIK-FRAMEWORK: PRE-MORTEM ANALYSE]
Setze voraus, dass das Projekt in 12 Monaten krisenhaft und vollständig gescheitert ist:
1. Geschichte des Scheiterns: Beschreibe das Totalschaden-Szenario.
2. Ursachen-Brainstorming: Verdeckte Risiken, fatale Annahmen, technische Schwachstellen.
3. Pre-emptive Maßnahmen: Sofortige Korrekturmaßnahmen zur Prävention jedes Scheiter-Grunds.
AUSGABE-FORMAT: [1. Das Scheiter-Szenario] | [2. Identifizierte Todesursachen] | [3. Präventive Schutzmaßnahmen]""",

        "Red Teaming / Adversarial Analysis": """[METHODIK-FRAMEWORK: RED TEAMING / ADVERSARIAL ATTACK]
Nimm die Rolle eines aggressiven externen Angreifers / Gegners ein:
1. Attack Vectors (Angriffsflächen): Schwachstellen in Logik, Sicherheit, Performance oder Usability.
2. Exploitation (Ausnutzung): Wie lässt sich die Lücke maximal ausnutzen?
3. Defensive Hardening (Härtung): Wie muss das System sofort gehärtet werden?
AUSGABE-FORMAT: ### Angriffsvektoren | ### Ausnutzungs-Szenario | ### Härtungs-Maßnahmen (Blue Team)""",

        "Six Thinking Hats (Edward de Bono)": """[METHODIK-FRAMEWORK: SIX THINKING HATS]
Analysiere die Aufgabe konsequent aus 6 getrennten Denkperspektiven:
⚪ Weiß (Fakten) | 🔴 Rot (Intuition) | 🖤 Schwarz (Kritik & Risiko) | 🟡 Gelb (Optimismus) | 🟢 Grün (Kreativität) | 🔵 Blau (Prozess & Synthese).
AUSGABE-FORMAT: Antworte geordnet nach den 6 Hüten: ⚪ Weiß | 🔴 Rot | 🖤 Schwarz | 🟡 Gelb | 🟢 Grün | 🔵 Blau""",

        "Inversion Thinking (Charlie Munger)": """[METHODIK-FRAMEWORK: INVERSION THINKING]
Löse das Problem durch konsequente Umkehrung (Inversion):
1. Das Worst-Case-Szenario: Definiere das absolute Scheitern des Vorhabens.
2. Garantierte Sabotage: Welche exakten Schritte, Entscheidungen und Unterlassungen führen mit 100%iger Sicherheit in dieses Szenario?
3. Anti-Muster: Leite aus den Sabotage-Schritten strikte Negativ-Regeln (Vermeidungs-Leitplanken) ab.
AUSGABE-FORMAT: [1. Das Worst-Case-Szenario] | [2. Sabotage-Wege] | [3. Anti-Muster (Was wir zwingend vermeiden)]""",

        "Walt-Disney-Methode": """[METHODIK-FRAMEWORK: WALT-DISNEY-METHODE]
Durchlaufe den dreistufigen Kreativitäts- und Prüfprozess strikt getrennt:
1. Der Träumer (Vision): Ignoriere Ressourcen und Einschränkungen. Was ist das utopische, maximale Potenzial der Idee?
2. Der Realisator (Machbarkeit): Wie kann der Traum technisch, finanziell und prozessual in einen konkreten Projektplan übersetzt werden?
3. Der Kritiker (Risiko): Wo sind die blinden Flecken, Fehler und Hürden im Plan des Realisators?
AUSGABE-FORMAT: [1. Traum (Vision)] | [2. Realität (Plan)] | [3. Kritik (Risiko)] | [4. Synthese]"""
    },

    "4. Strategie, Moat & Positionierung": {
        "Porter's Five Forces": """[METHODIK-FRAMEWORK: PORTER'S 5 FORCES BRANCHENANALYSE]
Bewerte die Wettbewerbsintensität und Branchenattraktivität:
1. Rivalität unter bestehenden Wettbewerbern
2. Bedrohung durch neue Anbieter (Eintrittsbarrieren)
3. Verhandlungsmacht der Lieferanten
4. Verhandlungsmacht der Abnehmer
5. Bedrohung durch Ersatzprodukte (Substitution)
STRATEGISCHE EMPFEHLUNG: Wie baut das System einen uneinnehmbaren Burggraben (Moat) auf?
AUSGABE-FORMAT: Analysiere die 5 Kräfte und schließe mit: ### Strategische Positionierung & Moat.""",

        "SWOT-Analyse": """[METHODIK-FRAMEWORK: STRATEGISCHE SWOT-ANALYSE]
Führe eine strukturierte Matrix-Analyse der internen und externen Faktoren durch:
- Interne Faktoren: Strengths (Stärken) & Weaknesses (Schwachstellen)
- Externe Faktoren: Opportunities (Chancen) & Threats (Risiken)
- TOWS-Strategieableitung: SO- und ST-Strategien ableiten.
AUSGABE-FORMAT: [Stärken] | [Schwächen] | [Chancen] | [Risiken] | [TOWS-Strategieableitung]""",

        "McKinsey 7S": """[METHODIK-FRAMEWORK: MCKINSEY 7S ORGANISATIONSANALYSE]
Analysiere die ganzheitliche Abstimmung des Systems über 7 Dimensionen:
- HARD S: Strategy, Structure, Systems.
- SOFT S: Shared Values, Style, Staff, Skills.
AUSGABE-FORMAT: Gliedere in [Hard S] und [Soft S] und zeige Diskrepanzen auf.""",

        "Wardley Mapping": """[METHODIK-FRAMEWORK: WARDLEY MAPPING]
Kartiere Systemkomponenten entlang der Wertschöpfungskette und Evolution:
1. User Need & Wertschöpfungskette (Sichtbar -> Unsichtbar)
2. Evolutionsstufen: Genesis -> Custom-Built -> Product/Rental -> Commodity/Utility
3. Strategischer Hebel: Welche Eigenbauten sollten durch Commodities ersetzt werden?
AUSGABE-FORMAT: ### Wertschöpfungskette | ### Evolutions-Mapping | ### Strategischer Hebel""",

        "VRIO-Analyse": """[METHODIK-FRAMEWORK: VRIO-ANALYSE]
Prüfe interne Ressourcen und Fähigkeiten auf nachhaltige Wettbewerbsvorteile:
1. Value (Wert): Schafft die Ressource einen direkten Wert oder senkt sie Kosten?
2. Rarity (Seltenheit): Ist die Ressource selten oder haben Wettbewerber leichten Zugriff?
3. Inimitability (Schwer imitierbar): Ist es teuer oder komplex, die Ressource zu kopieren?
4. Organization (Nutzung): Ist das System/Unternehmen aufgestellt, um dieses Potenzial abzuschöpfen?
AUSGABE-FORMAT: [1. Value] | [2. Rarity] | [3. Inimitability] | [4. Organization] | [5. Wettbewerbsvorteil]""",

        "Ansoff-Matrix": """[METHODIK-FRAMEWORK: ANSOFF-MATRIX]
Klassifiziere den strategischen Wachstumsvektor und das inhärente Risiko:
1. Marktdurchdringung (Bestehendes Produkt / Bestehender Markt): Wie erhöhen wir Conversion oder Frequenz?
2. Marktentwicklung (Bestehendes Produkt / Neuer Markt): Welche neuen Regionen oder Zielgruppen können adressiert werden?
3. Produktentwicklung (Neues Produkt / Bestehender Markt): Welches Upsell-/Cross-Sell-Produkt fehlt?
4. Diversifikation (Neues Produkt / Neuer Markt): Welches riskante Neugeschäft bietet exponentielles Wachstum?
AUSGABE-FORMAT: [1. Marktdurchdringung] | [2. Marktentwicklung] | [3. Produktentwicklung] | [4. Diversifikation]"""
    },

    "5. Marktanalyse, Nachfrage & Spieltheorie": {
        "STEEPLE / PESTEL": """[METHODIK-FRAMEWORK: STEEPLE / PESTEL ANALYSE]
Analysiere das externe Umfeld systematisch nach 7 Makro-Faktoren:
Social, Technological, Economic, Environmental, Political, Legal, Ethical.
AUSGABE-FORMAT: Führe für jeden Buchstaben [S], [T], [E], [E], [P], [L], [E] eine kurze Risiko- und Chancenbewertung durch.""",

        "NABC-Methode": """[METHODIK-FRAMEWORK: NABC PITCH & VALUE PROPOSITION]
Formuliere die Lösung als prägnanten Wertantrag (Pitch):
1. NEED (Bedürfnis): Welches konkrete, schmerzhafte Problem wird adressiert?
2. APPROACH (Ansatz): Wie sieht die innovative Lösung aus?
3. BENEFIT (Nutzen): Welchen quantifizierbaren Mehrwert/Ersparnis bringt der Ansatz?
4. COMPETITION (Wettbewerb): Warum ist dieser Ansatz besser als bestehende Alternativen?
AUSGABE-FORMAT: [Need] | [Approach] | [Benefit] | [Competition]""",

        "Spieltheorie & Payoff-Matrix": """[METHODIK-FRAMEWORK: SPIELTHEORIE & PAYOFF-MATRIX]
Analysiere die Situation als strategisches Spiel mit rationalen Akteuren:
1. Spieler & Ressourcen: Wer sind die Akteure, was sind ihre Handlungsoptionen?
2. Auszahlungsmatrix (Payoffs): Welchen Nutzen (Gewinn/Verlust) bringt jede Kombination von Zügen?
3. Nash-Gleichgewicht: Identifiziere den Zustand, bei dem kein Spieler durch einseitiges Abweichen seinen Nutzen steigern kann.
4. Minimax-Strategie: Welcher Zug minimiert den maximalen potenziellen Schaden?
AUSGABE-FORMAT: [1. Akteure & Optionen] | [2. Auszahlungsmatrix] | [3. Nash-Gleichgewicht] | [4. Minimax-Aktion]""",

        "Jobs to be Done (JTBD)": """[METHODIK-FRAMEWORK: JOBS TO BE DONE (JTBD)]
Analysiere die Nachfrage anhand des funktionalen, emotionalen und sozialen 'Jobs', für den die Lösung genutzt wird:
1. The Core Job: Welchen konkreten Fortschritt sucht der Nutzer?
2. Forces of Progress:
- Push: Warum ist der Status quo schmerzhaft?
- Pull: Welches Zielbild lockt?
- Anxiety: Welche Risiken blockieren die Entscheidung?
- Habit: Welche Routinen verhindern den Wechsel?
3. Success Metrics: Woran misst der Nutzer den Erfolg?
AUSGABE-FORMAT: [1. Core Job] | [2. Forces of Progress] | [3. Success Metrics]""",

        "Blue Ocean Strategy (ERRC-Grid)": """[METHODIK-FRAMEWORK: BLUE OCEAN STRATEGY (ERRC-GRID)]
Schaffe unumkämpfte Marktplätze durch Aufbrechen der Branchen-Kompromisse:
1. Eliminate (Eliminieren): Was gilt als Standard, bietet aber keinen Wert mehr und muss gestrichen werden?
2. Reduce (Reduzieren): Was wurde überdimensioniert und kann unter den Branchenstandard gesenkt werden?
3. Raise (Steigern): Was muss weit über den Standard gehoben werden?
4. Create (Kreieren): Was wurde in der Branche noch nie angeboten und muss erschaffen werden?
AUSGABE-FORMAT: [1. Eliminate] | [2. Reduce] | [3. Raise] | [4. Create]""",

        "TAM-SAM-SOM (Market Sizing)": """[METHODIK-FRAMEWORK: TAM-SAM-SOM MARKET SIZING]
Führe eine mathematische Marktgrößenbestimmung durch:
1. TAM (Total Addressable Market): Gesamtes theoretisches Marktvolumen (Kunden x Jahreswert).
2. SAM (Serviceable Addressable Market): Der Teil des TAM, der durch unsere Spezifikationen und Regionen abgedeckt wird.
3. SOM (Serviceable Obtainable Market): Der realistisch erreichbare Marktanteil in 1-3 Jahren.
4. Bottom-Up Plausibilisierung: Rechne SOM gegen die operativen Akquise-Kapazitäten.
AUSGABE-FORMAT: [1. TAM] | [2. SAM] | [3. SOM] | [4. Bottom-Up Validierung]"""
    },

    "6. Product-Launch & Growth Engineering": {
        "Kano-Modell": """[METHODIK-FRAMEWORK: KANO MERKMAL-ANALYSE]
Klassifiziere Features nach Auswirkung auf die Nutzerzufriedenheit:
1. Basis-Merkmale (Must-Haves) | 2. Leistungs-Merkmale (Linear) | 3. Begeisterungs-Merkmale (Delighters) | 4. Unerhebliche Merkmale.
AUSGABE-FORMAT: [Must-Haves] | [Performance-Features] | [Begeisterungs-Features]""",

        "Stage-Gate-Prozess": """[METHODIK-FRAMEWORK: STAGE-GATE-PROZESS]
Strukturiere die Entwicklung durch harte Go/Kill-Entscheidungstore:
Gate 1 (Scoping): Grobbewertung von Marktgröße und technischer Machbarkeit.
Gate 2 (Business Case): Detaillierte Finanzplanung, Unit Economics und Pflichtenheft.
Gate 3 (Development): Umsetzung, Prototyping und Alpha-Testing.
Gate 4 (Testing & Launch): Beta-Tests, QA-Freigabe und Rollout-Strategie.
AUSGABE-FORMAT: [Gate 1: Scoping] | [Gate 2: Business Case] | [Gate 3: Development] | [Gate 4: Testing & Launch]""",

        "Crossing the Chasm": """[METHODIK-FRAMEWORK: CROSSING THE CHASM]
Überwinde die Kluft zum pragmatischen Massenmarkt:
1. Beachhead Segment: Definiere eine extrem spitze, dominierbare Nische mit extremem Leidensdruck.
2. Whole Product: Welche Zusatzbausteine (Support, APIs, Docs) fehlen, um risikoscheue Kunden zu überzeugen?
3. Positioning: Positionierungs-Statement gegen den etablierten Marktführer.
4. Invasion Plan: Vertriebs- und Preisstrategie für den Brückenkopf.
AUSGABE-FORMAT: [1. Beachhead Nische] | [2. Whole Product] | [3. Positionierung] | [4. Invasionsplan]""",

        "Pirate Metrics (AARRR)": """[METHODIK-FRAMEWORK: PIRATE METRICS (AARRR)]
Analysiere die Funnel- und Wachstumsmetriken der Lösung:
1. Acquisition: Wie werden Nutzer auf das System/Produkt aufmerksam? (CAC, Kanäle).
2. Activation: Wie sieht das Aha-Erlebnis im ersten Kontakt aus? (Time-to-Value).
3. Retention: Warum kommen die Nutzer wieder? (Churn-Rate, Habits).
4. Referral: Wie wird das System von Nutzern weiterempfohlen? (Viralität).
5. Revenue: Wie wird monetarisiert? (Customer Lifetime Value - LTV).
AUSGABE-FORMAT: [1. Acquisition] | [2. Activation] | [3. Retention] | [4. Referral] | [5. Revenue]""",

        "Value Proposition Canvas": """[METHODIK-FRAMEWORK: VALUE PROPOSITION CANVAS]
Gleiche Kundenbedürfnisse mit dem Lösungsangebot ab:
1. Customer Profile: Pains, Gains, Jobs to be done.
2. Value Map: Pain Relievers, Gain Creators, Products & Services.
3. Der Fit: Deckt die Value Map das Customer Profile passgenau ab?
AUSGABE-FORMAT: [1. Customer Profile] | [2. Value Map] | [3. Der Fit]"""
    },

    "7. Business Model & Venture Building": {
        "Effectuation (Unternehmerische Mittelorientierung)": """[METHODIK-FRAMEWORK: EFFECTUATION]
Entwickle die Lösung strikt basierend auf den vorhandenen Mitteln statt auf vagen Prognosen:
1. Bird in Hand: Was ist JETZT vorhanden? (Fähigkeiten, Assets, Netzwerke, Kapital).
2. Affordable Loss: Was ist der maximale Verlust an Zeit/Geld, der zu 100% verkraftbar ist?
3. Crazy Quilt: Welche Partnerschaften können Unsicherheiten aus dem Markt nehmen?
4. Lemonade Principle: Welche aktuellen Fehler oder Marktkrisen lassen sich in einen Vorteil umwandeln?
AUSGABE-FORMAT: [1. Bird in Hand] | [2. Affordable Loss] | [3. Partnerschaften] | [4. Lemonade-Vorteil]""",

        "Lean Canvas": """[METHODIK-FRAMEWORK: LEAN CANVAS]
Dekomprimiere das Geschäftsmodell in 9 Blöcke:
1. Problem & Customer Segments: Die 3 größten Schmerzen und die Early Adopters.
2. Unique Value Proposition (UVP) & Solution: Das zentrale Wertversprechen und die Top 3 Features.
3. Channels & Unfair Advantage: Vertriebswege und der nicht-kopierbare Burggraben.
4. Cost Structure & Revenue Streams: Fixe/variable Kosten und die Monetarisierungsmechanik.
AUSGABE-FORMAT: [1. Problem & Zielgruppe] | [2. UVP & Lösung] | [3. Channels & Advantage] | [4. Erlöse & Kosten]""",

        "Unit Economics Engine (LTV/CAC)": """[METHODIK-FRAMEWORK: UNIT ECONOMICS ENGINE (LTV/CAC)]
Prüfe die finanzielle Tragfähigkeit und Skalierbarkeit:
1. Customer Acquisition Cost (CAC): Akquisekosten pro Neukunde.
2. Customer Lifetime Value (CLV/LTV): Netto-Deckungsbeitrag pro Kunde über die Haltedauer.
3. Ratio & Payback Period: LTV/CAC-Verhältnis (Ziel >3) und Amortisationsdauer in Monaten.
4. Deckungsbeitrag (DB): Kalkulation von Umsatz minus variablen System/Akquise-Kosten.
AUSGABE-FORMAT: [1. CAC] | [2. CLV] | [3. LTV/CAC Ratio & Payback] | [4. DB-Staffel]""",

        "Ten Types of Innovation": """[METHODIK-FRAMEWORK: TEN TYPES OF INNOVATION]
Identifiziere Innovationspotenziale abseits des reinen Kernprodukts:
1. Configuration (Backstage): Gewinnmodell, Netzwerke, interne Struktur, Kernprozesse.
2. Offering (Produkt): Produkt-Performance (Features) und Produkt-System (Ökosystem/Integrationen).
3. Experience (Frontend): Service, Vertriebskanäle, Marke, Customer Engagement.
AUSGABE-FORMAT: [1. Configuration] | [2. Offering] | [3. Experience] | [4. Stärkster Innovations-Hebel]""",

        "Flywheel-Framework (Jim Collins)": """[METHODIK-FRAMEWORK: FLYWHEEL-FRAMEWORK]
Identifiziere den sich selbst beschleunigenden Wachstumszyklus:
1. Input / Antriebskraft: Welche erste Handlung bringt das Rad in Schwung?
2. Frictionless Handoff: Wie führt dieser Input automatisch zum nächsten Schritt ohne Reibung?
3. Multipliers: Wie skaliert der Output exponentiell?
4. Das Loop: Wie speist das Ende des Prozesses den Anfang mit noch mehr Energie?
AUSGABE-FORMAT: [1. Antriebskraft] | [2. Reibungslose Übergabe] | [3. Verstärker] | [4. Das geschlossene Loop]"""
    },

    "8. Operations, Durchsatz & Qualität": {
        "DMAIC (Six Sigma)": """[METHODIK-FRAMEWORK: DMAIC (SIX SIGMA PROZESSOPTIMIERUNG)]
Sichere Qualität und eliminiere Prozessabweichungen in 5 Phasen:
[Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control]
AUSGABE-FORMAT: Strukturiere in die 5 Abschnitte: [Define] -> [Measure] -> [Analyze] -> [Improve] -> [Control].""",

        "PDCA-Zyklus (Demingkreis)": """[METHODIK-FRAMEWORK: PDCA CONTINUOUS IMPROVEMENT]
Durchlaufe den kontinuierlichen Verbesserungsprozess:
[Plan] -> [Do] -> [Check] -> [Act]
AUSGABE-FORMAT: Verwende die Abschnitte: ### Plan | ### Do | ### Check | ### Act""",

        "Theory of Constraints (TOC)": """[METHODIK-FRAMEWORK: THEORY OF CONSTRAINTS (ENGPASS-THEORIE)]
Maximiere den Durchsatz des gesamten Systems durch Fokussierung auf den primären Engpass (Bottleneck):
1. Identifizieren | 2. Ausnutzen | 3. Unterordnen | 4. Beseitigen | 5. Wiederholen.
AUSGABE-FORMAT: Gliedere in: [1. Primärer Engpass] | [2. Ausnutzung] | [3. Unterordnung] | [4. Behebung]""",

        "Eisenhower-Matrix": """[METHODIK-FRAMEWORK: EISENHOWER PRIORISIERUNGS-MATRIX]
Kategorisiere alle anstehenden Teilaufgaben strikt nach Wichtigkeit und Dringlichkeit:
[Quadrant I: Do First] | [Quadrant II: Schedule] | [Quadrant III: Delegate] | [Quadrant IV: Eliminate]
AUSGABE-FORMAT: [Quadrant I: Do] | [Quadrant II: Schedule] | [Quadrant III: Delegate] | [Quadrant IV: Eliminate]""",

        "FMEA (Failure Mode and Effects Analysis)": """[METHODIK-FRAMEWORK: FMEA RISIKO-QUANTIFIZIERUNG]
Bewerte Systemfehler quantitativ nach der Risikoprioritätszahl (RPN = A x B x E):
1. Fehlermöglichkeit | 2. Auftretenswahrscheinlichkeit (A: 1-10) | 3. Bedeutung (B: 1-10) | 4. Entdeckung (E: 1-10) | 5. RPN-Score.
AUSGABE-FORMAT: Tabellarische Liste: Component | Failure Mode | A | B | E | RPN | Massnahme""",

        "Nutzwertanalyse (Analytic Hierarchy Process - AHP)": """[METHODIK-FRAMEWORK: NUTZWERTANALYSE (AHP)]
Bewerte Handlungsalternativen quantitativ:
1. Kriterien & Gewichtung: Definiere 4-5 entscheidungsrelevante Kriterien und gewichte sie (Summe = 100%).
2. Alternativen: Liste die zu prüfenden Optionen auf.
3. Scoring: Werte jede Alternative pro Kriterium (1-10) und multipliziere mit der Gewichtung.
4. Sensitivitäts-Check: Ändert sich der Sieger, wenn das wichtigste Kriterium ignoriert wird?
AUSGABE-FORMAT: [1. Kriterien & Gewichtung] | [2. Scoring-Matrix] | [3. Sensitivitäts-Check] | [4. Sieger]"""
    },

    "9. Systemdenken, Risiko & Resilienz": {
        "Kotter 8-Stufen-Modell": """[METHODIK-FRAMEWORK: KOTTER CHANGE MANAGEMENT]
Strukturiere Transformation entlang der 8 Stufen des Change Managements:
1. Urgency | 2. Guiding Coalition | 3. Vision | 4. Communication | 5. Empowerment | 6. Short-Term Wins | 7. Consolidation | 8. Institutionalization.
AUSGABE-FORMAT: Liefere für jede der 8 Stufen eine konkrete Handlungsanweisung.""",

        "Causal Loop Diagrams (System Dynamics)": """[METHODIK-FRAMEWORK: CAUSAL LOOP DIAGRAMS]
Analysiere die Dynamik des Systems über Rückkopplungsschleifen:
1. System-Elemente | 2. Verstärkende Schleifen (R) | 3. Ausgleichende Schleifen (B) | 4. Zeitverzögerungen (Delays).
AUSGABE-FORMAT: [Variablen] | [Reinforcing Loops (R)] | [Balancing Loops (B)] | [Zeitverzögerungen]""",

        "Iceberg Model (Systems Thinking)": """[METHODIK-FRAMEWORK: DAS EISBERG-MODELL]
Dringe unter die Oberfläche des sichtbaren Problems vor:
1. Ereignisse (Symptom) -> 2. Muster & Trends -> 3. Systemstrukturen -> 4. Mentale Modelle (Fundament).
AUSGABE-FORMAT: [1. Ereignis] -> [2. Muster] -> [3. Struktur] -> [4. Mentales Modell]""",

        "Second-Order Thinking (Howard Marks)": """[METHODIK-FRAMEWORK: SECOND-ORDER THINKING]
Denke über unmittelbare Konsequenzen hinaus:
1. Effekte 1. Ordnung (Direkt) -> 2. Effekte 2. Ordnung (Nebenwirkungen) -> 3. Effekte 3. Ordnung (System-Shifts).
AUSGABE-FORMAT: [1st Order: Direkt] | [2nd Order: Nebenwirkungen] | [3rd Order: Systemwirkung]""",

        "Antifragilitäts-Analyse (Nassim Taleb)": """[METHODIK-FRAMEWORK: TALEB ANTIFRAGILITÄT]
Klassifiziere und optimiere das System:
1. Fragil (Bricht bei Stress) | 2. Robust (Hält stand) | 3. Antifragil (Lernt aus Fehlern und wird besser).
AUSGABE-FORMAT: ### Fragile Sollbruchstellen | ### Robuste Kernzonen | ### Antifragile Optimierungen""",

        "OODA-Loop (John Boyd)": """[METHODIK-FRAMEWORK: OODA-LOOP ECHTZEIT-STEUERUNG]
Durchlaufe den schnellen Orientierungs- und Entscheidungszirkel:
[Observe] -> [Orient] -> [Decide] -> [Act]
AUSGABE-FORMAT: [Observe] -> [Orient] -> [Decide] -> [Act]""",

        "Scenario Planning (Shell-Methode)": """[METHODIK-FRAMEWORK: SZENARIO-PLANUNG]
Entwickle 3 plausible Zukunftsszenarien:
1. Szenario A: Best Case / Growth | 2. Szenario B: Stagflation / Adversarial | 3. Szenario C: Black Swan.
AUSGABE-FORMAT: [Szenario A] | [Szenario B] | [Szenario C] | [No-Regret-Maßnahmen]""",

        "Crisis Escalation & Triage": """[METHODIK-FRAMEWORK: CRISIS ESCALATION & TRIAGE]
Führe strukturiertes Krisen- und Ad-hoc-Schadensmanagement durch:
1. Lagebild & Triage: Klassifizierung des Schadens (Systemausfall, PR-Gau, Rechtsbruch). Was blutet am stärksten?
2. Containment (Schadenseindämmung): Welche radikalen Maßnahmen stoppen die Blutung SOFORT?
3. Krisenkommunikation & Haftung: Wer muss informiert werden? Welche rechtlichen Pflichten greifen?
4. Recovery-Plan: Wie wird der Normalzustand wiederhergestellt und ein erneutes Auftreten verhindert?
AUSGABE-FORMAT: [1. Lagebild & Triage] | [2. Containment] | [3. Kommunikation & Haftung] | [4. Recovery & Prävention]"""
    }
}

# 2. Master Mapping: All 55 frameworks to profiles
FRAMEWORK_SLOT_DEFAULTS = {
    # 1. Agile, Lean & Innovation
    "CLEAR-Model": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Concise & Logical (Problemreduktion & Kausalität)", "default_profile": "system_architect_orchestrator"},
            {"role_name": "Explicit & Adaptive (Präzise Parameter & Alternativen)", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "Reflective Stresstest (Selbstkritik & Risikoprüfung)", "default_profile": "red_team_challenger"}
        ]
    },
    "CREATE-Framework": {
        "chair": "gtm_launch_strategist",
        "slots": [
            {"role_name": "Cue & Reaction (Auslöser & Intuitive Reaktion)", "default_profile": "direct_response_copywriter"},
            {"role_name": "Evaluation & Ability (Bewertung & Umsetzbarkeit)", "default_profile": "brand_uiux_director"},
            {"role_name": "Timing & Execute (Dringlichkeit & Ausführung)", "default_profile": "customer_retention_specialist"}
        ]
    },
    "Design Sprint (GV / Jake Knapp)": {
        "chair": "product_requirements_engineer",
        "slots": [
            {"role_name": "Map & Sketch (Problemraum & Lösungsskizzen)", "default_profile": "brand_uiux_director"},
            {"role_name": "Decide & Prototype (Entscheidung & Prototyp)", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "User Test & QA (Validierung & Feedback)", "default_profile": "customer_retention_specialist"}
        ]
    },
    "Double Diamond (Design Council)": {
        "chair": "brand_uiux_director",
        "slots": [
            {"role_name": "Discover (Problemfeld-Exploration & Research)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "Define & Develop (Problem-Definition & Lösungsspektrum)", "default_profile": "product_requirements_engineer"},
            {"role_name": "Deliver (Konvergente Umsetzung & Deployment)", "default_profile": "senior_fullstack_engineer"}
        ]
    },
    "Lean Startup (Eric Ries)": {
        "chair": "gtm_launch_strategist",
        "slots": [
            {"role_name": "Hypothese & MVP Build (Kleinstmögliches Testobjekt)", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "Measure & Metrics (Actionable Kennzahlen)", "default_profile": "database_performance_tuner"},
            {"role_name": "Learn - Pivot/Persevere (Validiertes Lernen)", "default_profile": "executive_decision_architect"}
        ]
    },
    "OKRs (Objectives and Key Results)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Objectives (Strategische Ausrichtung & Vision)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Key Results (Messbare quantitative Ziele)", "default_profile": "database_performance_tuner"},
            {"role_name": "Initiativen & Execution (Konkrete Arbeitspakete)", "default_profile": "agile_scrum_master"}
        ]
    },
    "Steffi Kieffer Boardroom": {
        "chair": "hermes_default",
        "slots": [
            {"role_name": "Skeptiker & Risikoprüfer (Bedenken & Hürden)", "default_profile": "red_team_challenger"},
            {"role_name": "Innovator & Optimist (Chancen & Zukunft)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Pragmatiker & Coder (Machbarkeit & Realisierung)", "default_profile": "senior_fullstack_engineer"}
        ]
    },

    # 2. Ursachenanalyse & Formale Logik
    "5-Why-Methode": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Root Cause Inquisitor (Bohrt 5 Stufen tief)", "default_profile": "red_team_challenger"},
            {"role_name": "Kausalität & Gegenmaßnahme (Nachhaltige Behebung)", "default_profile": "system_architect_orchestrator"}
        ]
    },
    "Cynefin-Framework (Dave Snowden)": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Domänen-Klassifizierung (Simple/Complicated/Complex/Chaotic)", "default_profile": "agile_scrum_master"},
            {"role_name": "Taktische Handlungsstrategie (Sense-Respond / Probe-Act)", "default_profile": "crisis_escalation_lead"}
        ]
    },
    "First Principles Thinking": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Dekonstruktion (Annahmen & Branchenmythen verwerfen)", "default_profile": "red_team_challenger"},
            {"role_name": "Grundfakten & Neuaufbau (Physik & Fundamente)", "default_profile": "senior_fullstack_engineer"}
        ]
    },
    "Ishikawa-Diagramm (6M)": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Mensch, Methode, Messung (Prozesse & Human Factors)", "default_profile": "agile_scrum_master"},
            {"role_name": "Maschine, Material, Milieu (Infrastruktur & Umgebung)", "default_profile": "devops_cloud_sec_specialist"}
        ]
    },
    "MECE-Issue-Tree": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Mutually Exclusive (Überschneidungsfreie Hypothesen)", "default_profile": "system_architect_orchestrator"},
            {"role_name": "Collectively Exhaustive (Lückenlose Vollständigkeit)", "default_profile": "red_team_challenger"}
        ]
    },
    "TRIZ (Widerspruchsmatrix)": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "System-Widerspruch & Parameter-Mapping", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "Innovationsprinzipien & Technische Lösung", "default_profile": "product_requirements_engineer"}
        ]
    },

    # 3. Kognitive Entzerrung & Debatte
    "Ladder of Inference (Chris Argyris)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Rohdaten & Selektion (Faktenbasis ohne Filter)", "default_profile": "database_performance_tuner"},
            {"role_name": "Annahmen & Schlussfolgerungen (Kognitiver Stresstest)", "default_profile": "red_team_challenger"}
        ]
    },
    "Pre-Mortem Analyse (Gary Klein)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Szenario des Totalschadens & Todesursachen", "default_profile": "crisis_escalation_lead"},
            {"role_name": "Präventive Sofortmaßnahmen (Schutzschilde)", "default_profile": "devops_cloud_sec_specialist"}
        ]
    },
    "Red Teaming / Adversarial Analysis": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Red Team Attacker & Exploitation (Angriffsvektoren)", "default_profile": "red_team_challenger"},
            {"role_name": "Blue Team Defensive Hardening (Systemhärtung)", "default_profile": "devops_cloud_sec_specialist"}
        ]
    },
    "Six Thinking Hats (Edward de Bono)": {
        "chair": "hermes_default",
        "slots": [
            {"role_name": "⚪ Weißer Hut (Fakten & Daten)", "default_profile": "database_performance_tuner"},
            {"role_name": "🔴 Roter Hut (Intuition & Emotion)", "default_profile": "storyteller_ghostwriter"},
            {"role_name": "🖤 Schwarzer Hut (Risiken & Kritik)", "default_profile": "red_team_challenger"},
            {"role_name": "🟡 Gelber Hut (Optimismus & Chancen)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "🟢 Grüner Hut (Kreativität & Alternativen)", "default_profile": "brand_uiux_director"}
        ]
    },
    "Inversion Thinking (Charlie Munger)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Worst-Case-Szenario & Garantierte Sabotage", "default_profile": "red_team_challenger"},
            {"role_name": "Anti-Muster & Vermeidungs-Leitplanken", "default_profile": "system_architect_orchestrator"}
        ]
    },
    "Walt-Disney-Methode": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Der Träumer (Utopisches Maximalpotenzial & Vision)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Der Realisator (Technische & prozessuale Machbarkeit)", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "Der Kritiker (Risikoanalyse & blinde Flecken)", "default_profile": "red_team_challenger"}
        ]
    },

    # 4. Strategie, Moat & Positionierung
    "Porter's Five Forces": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Rivalität & Substitution (Wettbewerbsdruck)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "Lieferanten- & Abnehmermacht (Marktverhandlungsmacht)", "default_profile": "procurement_sourcing_scout"},
            {"role_name": "Neue Anbieter & Moat (Barrieren & Burggraben)", "default_profile": "gtm_launch_strategist"}
        ]
    },
    "SWOT-Analyse": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Interne Stärken (Kernkompetenzen & Assets)", "default_profile": "system_architect_orchestrator"},
            {"role_name": "Interne Schwachstellen (Bottlenecks & Risiken)", "default_profile": "red_team_challenger"},
            {"role_name": "Externe Chancen (Marktpotenziale & Trends)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "Externe Risiken (Regulierung & Marktdruck)", "default_profile": "liability_risk_analyst"}
        ]
    },
    "McKinsey 7S": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Hard S (Strategy, Structure, Systems)", "default_profile": "enterprise_solutions_architect"},
            {"role_name": "Soft S (Shared Values, Style, Staff, Skills)", "default_profile": "labor_law_hr_governance"}
        ]
    },
    "Wardley Mapping": {
        "chair": "enterprise_solutions_architect",
        "slots": [
            {"role_name": "User Need & Wertschöpfungskette (Sichtbare Schichten)", "default_profile": "product_requirements_engineer"},
            {"role_name": "Evolutions-Mapping & Commodity-Hebung (Tech-Strategie)", "default_profile": "system_architect_orchestrator"}
        ]
    },
    "VRIO-Analyse": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Value & Rarity (Wertschöpfung & Seltenheit)", "default_profile": "ip_patent_analyst"},
            {"role_name": "Inimitability & Organization (Kopierschutz & Struktur)", "default_profile": "liability_risk_analyst"}
        ]
    },
    "Ansoff-Matrix": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Marktdurchdringung & Marktentwicklung", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Produktentwicklung & Diversifikation", "default_profile": "arbitrage_market_analyst"}
        ]
    },

    # 5. Marktanalyse, Nachfrage & Spieltheorie
    "STEEPLE / PESTEL": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Social, Tech, Economic (Markt & Technologie)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "Political, Legal, Ethical, Env (Compliance & Umwelt)", "default_profile": "compliance_gdpr_auditor"}
        ]
    },
    "NABC-Methode": {
        "chair": "pitchdeck_offer_designer",
        "slots": [
            {"role_name": "Need & Benefit (Kundenbedürfnis & Mehrwert)", "default_profile": "customer_retention_specialist"},
            {"role_name": "Approach & Tech-Lösung (Konkreter Lösungsansatz)", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "Competition & Differenzierung (Wettbewerbsvorteil)", "default_profile": "competitive_intelligence_scout"}
        ]
    },
    "Spieltheorie & Payoff-Matrix": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Akteure, Optionen & Payoffs (Auszahlungsmatrix)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "Nash-Gleichgewicht & Minimax-Aktion (Schadensbegrenzung)", "default_profile": "database_performance_tuner"}
        ]
    },
    "Jobs to be Done (JTBD)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Core Job & Push/Pull Forces (Kundenfortschritt)", "default_profile": "customer_retention_specialist"},
            {"role_name": "Anxieties, Habits & Success Metrics (Wechselbarrieren)", "default_profile": "direct_response_copywriter"}
        ]
    },
    "Blue Ocean Strategy (ERRC-Grid)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Eliminate & Reduce (Kostensenkung & Entschlackung)", "default_profile": "system_architect_orchestrator"},
            {"role_name": "Raise & Create (Neue Wertkurve & Innovation)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Branchenstandard & Differenzierung (Wettbewerbsabgrenzung)", "default_profile": "competitive_intelligence_scout"}
        ]
    },
    "TAM-SAM-SOM (Market Sizing)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "TAM & SAM (Theoretisches Marktvolumen & Segment)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "SOM & Bottom-Up Validierung (Operativ erreichbarer Anteil)", "default_profile": "pricing_discount_governor"}
        ]
    },

    # 6. Product-Launch & Growth Engineering
    "Kano-Modell": {
        "chair": "product_requirements_engineer",
        "slots": [
            {"role_name": "Basis- & Leistungsmerkmale (Must-Haves & Performance)", "default_profile": "brand_uiux_director"},
            {"role_name": "Begeisterungsmerkmale & Delighters (Aha-Effekte)", "default_profile": "customer_retention_specialist"}
        ]
    },
    "Stage-Gate-Prozess": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Gate 1 Scoping & Gate 2 Business Case (Planung)", "default_profile": "product_requirements_engineer"},
            {"role_name": "Gate 3 Development & Testing (Umsetzung & Alpha)", "default_profile": "senior_fullstack_engineer"},
            {"role_name": "Gate 4 Launch & Rollout (Go-to-Market Freigabe)", "default_profile": "gtm_launch_strategist"}
        ]
    },
    "Crossing the Chasm": {
        "chair": "gtm_launch_strategist",
        "slots": [
            {"role_name": "Beachhead Segment & Invasionsplan (Spitze Nische)", "default_profile": "b2b_outreach_specialist"},
            {"role_name": "Whole Product & Positionierung (Risikosenkung)", "default_profile": "product_requirements_engineer"}
        ]
    },
    "Pirate Metrics (AARRR)": {
        "chair": "gtm_launch_strategist",
        "slots": [
            {"role_name": "Acquisition & Activation (Traffic & Time-to-Value)", "default_profile": "lead_enrichment_analyst"},
            {"role_name": "Retention & Referral (Kundenbindung & Viralität)", "default_profile": "customer_retention_specialist"},
            {"role_name": "Revenue & Monetarisierung (LTV & Margen)", "default_profile": "pricing_discount_governor"}
        ]
    },
    "Value Proposition Canvas": {
        "chair": "pitchdeck_offer_designer",
        "slots": [
            {"role_name": "Customer Profile (Pains, Gains, Jobs)", "default_profile": "customer_retention_specialist"},
            {"role_name": "Value Map & Fit (Pain Relievers & Gain Creators)", "default_profile": "direct_response_copywriter"}
        ]
    },

    # 7. Business Model & Venture Building
    "Effectuation (Unternehmerische Mittelorientierung)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Bird in Hand & Affordable Loss (Mittel & Verlustgrenzen)", "default_profile": "personal_life_strategist"},
            {"role_name": "Crazy Quilt Partnerschaften & Lemonade Principle", "default_profile": "arbitrage_market_analyst"}
        ]
    },
    "Lean Canvas": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Problem, UVP & Channels (Kundenzentrierung)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Kostenstruktur, Erlösströme & Unfair Advantage", "default_profile": "pricing_discount_governor"}
        ]
    },
    "Unit Economics Engine (LTV/CAC)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "CAC, LTV & Payback Period (Amortisationsanalyse)", "default_profile": "pricing_discount_governor"},
            {"role_name": "Deckungsbeitrag & Skalierbarkeit (Unit Profitability)", "default_profile": "database_performance_tuner"}
        ]
    },
    "Ten Types of Innovation": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Configuration - Backstage (Profit Model & Network)", "default_profile": "pricing_discount_governor"},
            {"role_name": "Offering - Produkt (Performance & Product System)", "default_profile": "product_requirements_engineer"},
            {"role_name": "Experience - Frontend (Brand, Channel & Customer)", "default_profile": "brand_uiux_director"}
        ]
    },
    "Flywheel-Framework (Jim Collins)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Antriebskraft & Frictionless Handoff (Erste Energie)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Multipliers & Closed Loop (Selbstverstärkung)", "default_profile": "customer_retention_specialist"}
        ]
    },

    # 8. Operations, Durchsatz & Qualität
    "DMAIC (Six Sigma)": {
        "chair": "agile_scrum_master",
        "slots": [
            {"role_name": "Define & Measure (Problem & Ist-Metriken)", "default_profile": "database_performance_tuner"},
            {"role_name": "Analyze & Improve (Ursachen & Optimierung)", "default_profile": "system_architect_orchestrator"},
            {"role_name": "Control & Monitoring (Dauerhafte Standards)", "default_profile": "devops_cloud_sec_specialist"}
        ]
    },
    "PDCA-Zyklus (Demingkreis)": {
        "chair": "agile_scrum_master",
        "slots": [
            {"role_name": "Plan & Do (Konzeption & Pilotierung)", "default_profile": "product_requirements_engineer"},
            {"role_name": "Check & Act (Messung & Standardisierung)", "default_profile": "devops_cloud_sec_specialist"}
        ]
    },
    "Theory of Constraints (TOC)": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Engpass-Diagnostik (System-Bottleneck finden)", "default_profile": "database_performance_tuner"},
            {"role_name": "Durchsatz-Optimierung & Ausbau (Engpass-Hebung)", "default_profile": "logistics_supply_chain_manager"}
        ]
    },
    "Eisenhower-Matrix": {
        "chair": "personal_life_strategist",
        "slots": [
            {"role_name": "Do First & Delegate (Dringende operative Tasks)", "default_profile": "crisis_escalation_lead"},
            {"role_name": "Schedule & Eliminate (Strategische Langzeitfokusse)", "default_profile": "executive_decision_architect"}
        ]
    },
    "FMEA (Failure Mode and Effects Analysis)": {
        "chair": "devops_cloud_sec_specialist",
        "slots": [
            {"role_name": "Schweregrad / Bedeutung B (Impact auf Nutzer/System)", "default_profile": "liability_risk_analyst"},
            {"role_name": "Auftretenswahrscheinlichkeit A (Fehlerursachen)", "default_profile": "system_architect_orchestrator"},
            {"role_name": "Entdeckungssicherheit E (Monitoring & Früherkennung)", "default_profile": "senior_fullstack_engineer"}
        ]
    },
    "Nutzwertanalyse (Analytic Hierarchy Process - AHP)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Kriterien & Alternativen (Kriterien-Hierarchie)", "default_profile": "product_requirements_engineer"},
            {"role_name": "Scoring, Gewichtung & Sensitivitäts-Check", "default_profile": "database_performance_tuner"}
        ]
    },

    # 9. Systemdenken, Risiko & Resilienz
    "Kotter 8-Stufen-Modell": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Urgency, Coalition & Vision (Phasen 1-4)", "default_profile": "storyteller_ghostwriter"},
            {"role_name": "Empowerment, Wins & Verankerung (Phasen 5-8)", "default_profile": "labor_law_hr_governance"}
        ]
    },
    "Causal Loop Diagrams (System Dynamics)": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Verstärkende Schleifen (Reinforcing Loops / Feedback)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Ausgleichende Schleifen & Delays (Balancing Loops)", "default_profile": "logistics_supply_chain_manager"}
        ]
    },
    "Iceberg Model (Systems Thinking)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Symptome & Muster (Ereignisse unter der Oberfläche)", "default_profile": "crisis_escalation_lead"},
            {"role_name": "Systemstrukturen & Mentale Modelle (Tiefenarchitektur)", "default_profile": "system_architect_orchestrator"}
        ]
    },
    "Second-Order Thinking (Howard Marks)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Effekte 1. Ordnung (Unmittelbar & Offensichtlich)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Effekte 2. & 3. Ordnung (Nebenwirkungen & System-Shifts)", "default_profile": "red_team_challenger"}
        ]
    },
    "Antifragilitäts-Analyse (Nassim Taleb)": {
        "chair": "system_architect_orchestrator",
        "slots": [
            {"role_name": "Fragile Sollbruchstellen (Stressanfälligkeit)", "default_profile": "red_team_challenger"},
            {"role_name": "Antifragile Feedback-Loops (Lernen aus Störungen)", "default_profile": "devops_cloud_sec_specialist"}
        ]
    },
    "OODA-Loop (John Boyd)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Observe & Orient (Lageerfassung & Filterung)", "default_profile": "competitive_intelligence_scout"},
            {"role_name": "Decide & Act (Entscheidung & Blitzschnelle Ausführung)", "default_profile": "agile_scrum_master"}
        ]
    },
    "Scenario Planning (Shell-Methode)": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Szenario A: Best Case / Growth (Optimale Skalierung)", "default_profile": "gtm_launch_strategist"},
            {"role_name": "Szenario B: Stagflation / Adversarial (Stress & Ausfälle)", "default_profile": "crisis_escalation_lead"},
            {"role_name": "Szenario C & No-Regret Moves (Black Swan & Resilienz)", "default_profile": "red_team_challenger"}
        ]
    },
    "Crisis Escalation & Triage": {
        "chair": "executive_decision_architect",
        "slots": [
            {"role_name": "Lagebild, Triage & Containment (Schadenseindämmung)", "default_profile": "crisis_escalation_lead"},
            {"role_name": "Krisenkommunikation, Haftung & Recovery", "default_profile": "liability_risk_analyst"}
        ]
    }
}

print(f"Total categories: {len(CATEGORIZED_FRAMEWORKS)}")
print(f"Total frameworks: {len(FRAMEWORK_SLOT_DEFAULTS)}")
