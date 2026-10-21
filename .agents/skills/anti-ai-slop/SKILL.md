---
name: anti-ai-slop
description: Erkennt und bereinigt typische KI-Floskeln, Marketing-Slop, Höflichkeitsfloskeln und formelhafte LLM-Muster nach dem Vorbild von SlopMonster.
version: 1.0.0
author: Archon OS Intelligence
category: Text-Postprocessing & Qualitätssicherung
tags: ["anti-slop", "copy-editing", "slopmonster", "human-voice", "postprocessing"]
---

# 🧹 Anti-AI-Slop & Tone Optimizer (SlopMonster Engine)

Dieses Skill bereinigt generierte Texte, Berichte und Systemausgaben von typischen KI-Floskeln („AI-Slop“), künstlicher Euphorie und formelhaften Phrasen. Es sorgt für einen präzisen, aktiven und menschlich wirkenden Sprachstil.

---

## 1. Gesperrte Wörter & Phrasen (Blacklist)

### Tier 1: Typische KI-Füllwörter
* ❌ *delve / eintauchen*
* ❌ *tapestry / Teppich / Gewebe*
* ❌ *realm / Reich / Sphäre*
* ❌ *nestled / eingebettet*
* ❌ *vibrant / lebendig / pulsierend*
* ❌ *testament to / Zeugnis von*
* ❌ *beacon / Leuchtturm*
* ❌ *pivotal / entscheidend / Dreh- und Angelpunkt*
* ❌ *robust / cutting-edge / comprehensive / state-of-the-art*
* ❌ *at its core / im Kern / dient als*
* ❌ *boasts / besticht durch / verfügt stolz über*
* ❌ *in order to / um zu (wenn verkürzbar)*

### Tier 2: Redundante Überleitungen
* ❌ *Moreover / Darüber hinaus*
* ❌ *Furthermore / Weiterhin*
* ❌ *Additionally / Zusätzlich*
* ❌ *Notably / Bemerkenswert ist*
* ❌ *It is important to note that / Es ist wichtig zu beachten, dass*
* ❌ *In conclusion / Zusammenfassend lässt sich sagen*

### Tier 3: Chatbot-Tics & Schmeicheleien
* ❌ *„Gute Frage!“, „Sehr gerne!“, „Sicherlich!“, „Absolut!“*
* ❌ *„Ich hoffe, das hilft dir weiter!“, „Lass mich wissen, falls du noch Fragen hast.“*
* ❌ *Künstliche Höflichkeitsfloskeln am Anfang oder Ende einer Antwort.*

---

## 2. Bereinigungs- und Umschreibregeln

1. **Aktiv statt Passiv:**
   * Vorher: *„Die Implementierung wurde durch das Team durchgeführt.“*
   * Nachher: *„Das Team implementierte das Modul.“*
2. **Konkret statt Vage:**
   * Vorher: *„Das System bietet eine enorme Leistungssteigerung.“*
   * Nachher: *„Die Latenz sank von 450 ms auf 80 ms.“*
3. **Satzlängen variieren:**
   * Keine gleichförmigen 20-Wort-Sätze aneinanderreihen. Kurze, prägnante Sätze mit punktuellen Erklärungen abwechseln.
4. **Keine formelhaften Drei-Punkte-Zusammenfassungen:**
   * Nicht jeden Absatz mit einer rhetorischen Frage oder einer dreiteiligen Aufzählung beenden.

---

## 3. Workflow zur Textbereinigung

Wenn dieses Skill auf einen Entwurf angewendet wird:
1. **Scan:** Prüfe den Text gegen die obigen Blacklists.
2. **Kürzung:** Streiche alle einleitenden und abschließenden Höflichkeitsfloskeln restlos.
3. **Substantiv-Diät:** Ersetze nominalisierte Konstruktionen („Durchführung der Prüfung“) durch direkte Verben („prüfen“).
4. **Verdichtung:** Reduziere die Wortanzahl um ca. 20–30 %, ohne Fakten oder technische Details zu entfernen.
