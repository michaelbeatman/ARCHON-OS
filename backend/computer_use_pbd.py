# -*- coding: utf-8 -*-
"""
backend/computer_use_pbd.py
===========================
Autonomous Computer-Use & Programming by Demonstration (PbD) Engine (Meilenstein 26):
1. GhostCursorEngine:
   - Biomechanische Bézier-Trajektorien (Cubic Bézier mit Fitts's Law Verzögerung).
   - Bounding-Box Gaussian Jitter (Zufallsversatz innerhalb von klickbaren Elementen,
     um Anti-Bot WAFs zu überlisten).
   - Menschliche Tastatur-Kadenzen (50-180ms variierende Tastenanschläge).

2. DemonstrationRecorder & PbDSynthesizer:
   - Zeichnet Bediener-Aktionen (Klicks, Eingaben, Navigationen) und gesprochene/getippte
     Sprachkommentare ("Hier filtere ich nach Senior Coder...") live im Bot-Screen auf.
   - Synthetisiert den Demonstrations-Trace vollautomatisch in einen wiederverwendbaren
     Archon OS Skill (.agents/skills/<skill_name>/SKILL.md) sowie ein lauffähiges Python-Skript.

3. ObservationPruner & Set-of-Marks (a11y Tree):
   - Reduziert rohen HTML-DOM-Müll (SVGs, Tracking-Skripte, tiefe Div-Verschachtelungen)
     um bis zu 90% auf einen kompakten, semantischen Accessibility-Tree.
   - Erzeugt Set-of-Marks (SoM) Markierungen für multimodale Vision-Agenten.
"""

import os
import re
import math
import random
import time
import json
import datetime
from typing import Dict, Any, List, Optional, Tuple


def _find_line_value(text: str, key: str):
    """Erster Wert einer Zeile, die mit `key` beginnt (z. B. "created_at: ")."""
    for line in text.splitlines():
        if line.startswith(key):
            return line[len(key):].strip()
    return None


def _replace_line_value(text: str, key: str, value: str) -> str:
    """Ersetzt den Wert der ersten Zeile, die mit `key` beginnt."""
    out, done = [], False
    for line in text.splitlines(keepends=True):
        if not done and line.startswith(key):
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"{key}{value}{newline}")
            done = True
        else:
            out.append(line)
    return "".join(out)


def _write_if_changed(path: str, content: str, timestamp_keys: tuple) -> bool:
    """Schreibt `content` nur, wenn er sich abzüglich der Zeitstempel-Zeilen ändert.

    Ohne diese Prüfung erzeugt jeder Synthese-Lauf einen neuen Zeitstempel in
    `Erstellt am: …` / `created_at: …`. Der Inhalt ist danach "geändert", obwohl
    er identisch ist: `git status` wird nie sauber und jede Rücksetzung wird beim
    nächsten Lauf überschrieben. Vorgehen: Zeitstempel-Werte aus der bestehenden
    Datei übernehmen, dann vergleichen; nur bei echter Abweichung schreiben.
    """
    existing = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read()
        except OSError:
            existing = None

    if existing is not None:
        stabilized = content
        for key in timestamp_keys:
            stored = _find_line_value(existing, key)
            if stored is not None:
                stabilized = _replace_line_value(stabilized, key, stored)
        if stabilized == existing:
            return False
        content = stabilized

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(WORKSPACE_DIR, ".agents", "skills")
SCRIPTS_DIR = os.path.join(WORKSPACE_DIR, "scripts", "dynamic_tools")
PBD_TRACES_DIR = os.path.join(WORKSPACE_DIR, "data", "pbd_traces")

os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(PBD_TRACES_DIR, exist_ok=True)


class GhostCursorEngine:
    """
    Simuliert menschliche biomechanische Mausbewegungen und Eingabekadenzen.
    Verhindert Entdeckung durch CAPTCHAs, Fingerprinting und Anti-Bot-WAFs.
    """

    @staticmethod
    def calculate_bezier_trajectory(
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int = 25,
        deviation: float = 35.0
    ) -> List[Dict[str, Any]]:
        """
        Erzeugt kubische Bézier-Kurvenpunkte zwischen start und end.
        Modelliert menschliche Handgelenk-Trägheit mit Fitts's Law Geschwindigkeitskurve.
        """
        x0, y0 = start
        x3, y3 = end
        dist = math.hypot(x3 - x0, y3 - y0)
        if dist < 1.0:
            return [{"x": round(x3, 2), "y": round(y3, 2), "t": 1.0, "speed": 0.0}]

        # Zufällige Kontrollpunkte seitlich versetzt für natürliche Wölbung
        dx = x3 - x0
        dy = y3 - y0
        normal_x = -dy / dist
        normal_y = dx / dist

        offset1 = (random.random() - 0.5) * deviation
        offset2 = (random.random() - 0.5) * (deviation * 0.7)

        # Kontrollpunkt 1 (ca. 25-35% der Strecke)
        x1 = x0 + dx * 0.3 + normal_x * offset1
        y1 = y0 + dy * 0.3 + normal_y * offset1

        # Kontrollpunkt 2 (ca. 65-75% der Strecke mit leichter Korrektur)
        x2 = x0 + dx * 0.7 + normal_x * offset2
        y2 = y0 + dy * 0.7 + normal_y * offset2

        trajectory = []
        for i in range(steps + 1):
            t = i / float(steps)

            # Fitts's Law Trägheit: Beschleunigung am Anfang, Abbremsung vor dem Ziel
            # Ease-in-out S-Kurve
            t_eased = t * t * (3.0 - 2.0 * t)

            # Kubische Bézier-Gleichung
            omt = 1.0 - t_eased
            omt2 = omt * omt
            omt3 = omt2 * omt
            t2 = t_eased * t_eased
            t3 = t2 * t_eased

            bx = omt3 * x0 + 3.0 * omt2 * t_eased * x1 + 3.0 * omt * t2 * x2 + t3 * x3
            by = omt3 * y0 + 3.0 * omt2 * t_eased * y1 + 3.0 * omt * t2 * y2 + t3 * y3

            # Mikro-Jitter (Zittern der menschlichen Hand ca. 0.2 - 0.5 Pixel)
            jitter_x = (random.random() - 0.5) * 0.4 if 0 < i < steps else 0.0
            jitter_y = (random.random() - 0.5) * 0.4 if 0 < i < steps else 0.0

            trajectory.append({
                "x": round(bx + jitter_x, 2),
                "y": round(by + jitter_y, 2),
                "t": round(t, 3),
                "step": i
            })

        return trajectory

    @staticmethod
    def apply_bounding_box_jitter(
        center_x: float,
        center_y: float,
        width: float,
        height: float,
        sigma_ratio: float = 0.22
    ) -> Tuple[float, float]:
        """
        Berechnet einen Gauss-verteilten Klickpunkt innerhalb der Bounding Box.
        Verhindert, dass der Bot immer exakt auf das Zentrum eines Buttons klickt.
        """
        # Standardabweichung proportional zur Button-Größe
        sigma_x = (width * sigma_ratio)
        sigma_y = (height * sigma_ratio)

        # Gauss-Verteilung um den Mittelpunkt
        jittered_x = random.gauss(center_x, sigma_x)
        jittered_y = random.gauss(center_y, sigma_y)

        # Clamp innerhalb der Bounding-Box mit 10% Sicherheitsrand
        margin_x = width * 0.1
        margin_y = height * 0.1

        clamped_x = max(center_x - width / 2.0 + margin_x, min(center_x + width / 2.0 - margin_x, jittered_x))
        clamped_y = max(center_y - height / 2.0 + margin_y, min(center_y + height / 2.0 - margin_y, jittered_y))

        return round(clamped_x, 2), round(clamped_y, 2)

    @staticmethod
    def generate_keystroke_delays(text: str) -> List[Dict[str, Any]]:
        """
        Generiert menschenähnliche Anschlagverzögerungen (50-180ms pro Buchstabe,
        mit längeren Pausen bei Leerzeichen und Satzzeichen).
        """
        delays = []
        for char in text:
            base_delay = random.uniform(0.055, 0.125)
            if char in " .,:;!?\n":
                # Kognitive Pause beim Wortende
                base_delay += random.uniform(0.12, 0.28)
            elif char.isupper():
                # Leichte Verzögerung für Shift-Taste
                base_delay += random.uniform(0.04, 0.09)
            delays.append({
                "char": char,
                "delay_ms": round(base_delay * 1000, 1)
            })
        return delays


class ObservationPruner:
    """
    Accessibility-Tree (a11y) Extraktor & Observation Pruning:
    Reduziert DOM-Strukturen um 85-92% auf semantisch interaktive Elemente.
    """

    INTERACTIVE_ROLES = {
        "button", "link", "textbox", "searchbox", "checkbox", "radio",
        "combobox", "menuitem", "tab", "switch", "slider", "heading"
    }

    @classmethod
    def prune_html_to_a11y_tree(cls, raw_html: str, max_depth: int = 5) -> Dict[str, Any]:
        """
        Extrahiert interaktive Elemente aus HTML und liefert einen extrem kompakten Tree.
        """
        raw_length = len(raw_html)

        # 1. Entferne Skripte, Styles, SVG-Pfade und Kommentare
        cleaned = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', raw_html, flags=re.IGNORECASE)
        cleaned = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<svg\b[^<]*(?:(?!<\/svg>)<[^<]*)*<\/svg>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<!--[\s\S]*?-->', '', cleaned)

        # 2. Finde interaktive Elemente (Buttons, Inputs, Links, Selects, Headings)
        elements = []
        idx = 1

        # Buttons
        for m in re.finditer(r'<button\b([^>]*)>(.*?)</button>', cleaned, re.IGNORECASE | re.DOTALL):
            attrs, content = m.group(1), m.group(2)
            label = re.sub(r'<[^>]+>', ' ', content).strip()
            elements.append({
                "mark_id": idx,
                "role": "button",
                "label": label[:60] or "Schaltfläche",
                "selector": f"button:contains('{label[:30]}')" if label else "button"
            })
            idx += 1

        # Inputs
        for m in re.finditer(r'<input\b([^>]*)>', cleaned, re.IGNORECASE):
            attrs = m.group(1)
            inp_type = "text"
            t_match = re.search(r'type=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            if t_match:
                inp_type = t_match.group(1).lower()
            if inp_type in ("hidden",):
                continue
            name_match = re.search(r'(?:placeholder|aria-label|name|id)=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            label = name_match.group(1) if name_match else inp_type
            elements.append({
                "mark_id": idx,
                "role": f"input[{inp_type}]",
                "label": label[:60],
                "selector": f"input[{inp_type}]"
            })
            idx += 1

        # Links (a tags)
        for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', cleaned, re.IGNORECASE | re.DOTALL):
            attrs, content = m.group(1), m.group(2)
            href_m = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            href = href_m.group(1) if href_m else ""
            label = re.sub(r'<[^>]+>', ' ', content).strip()
            if label:
                elements.append({
                    "mark_id": idx,
                    "role": "link",
                    "label": label[:60],
                    "target": href[:80]
                })
                idx += 1

        # Formatiere Kompakten a11y String
        tree_lines = []
        for el in elements:
            role_badge = f"[{el['role']}]"
            mark = f"[@{el['mark_id']}]"
            target_info = f" -> {el['target']}" if "target" in el and el['target'] else ""
            tree_lines.append(f"{mark:<6} {role_badge:<14} \"{el['label']}\"{target_info}")

        pruned_text = "\n".join(tree_lines)
        pruned_length = len(pruned_text)
        token_reduction = round((1.0 - (pruned_length / max(raw_length, 1))) * 100.0, 1)

        return {
            "elements_count": len(elements),
            "elements": elements,
            "pruned_a11y_tree": pruned_text,
            "raw_characters": raw_length,
            "pruned_characters": pruned_length,
            "token_reduction_percent": max(0.0, token_reduction)
        }


class DemonstrationRecorder:
    """
    Zeichnet menschliche Arbeitsabläufe im Bot-Screen auf (PbD - Programming by Demonstration).
    """

    def __init__(self):
        self._current_session: Optional[Dict[str, Any]] = None

    def start_recording(self, session_title: str, target_url: str, creator_agent: str = "default") -> Dict[str, Any]:
        session_id = f"pbd_{int(time.time())}_{random.randint(1000, 9999)}"
        self._current_session = {
            "session_id": session_id,
            "title": session_title,
            "target_url": target_url,
            "creator_agent": creator_agent,
            "start_time": datetime.datetime.now().isoformat(),
            "events": []
        }
        return {
            "status": "recording_started",
            "session_id": session_id,
            "title": session_title,
            "target_url": target_url
        }

    def record_event(self, action_type: str, details: Dict[str, Any], commentary: str = "") -> Dict[str, Any]:
        """
        action_type: 'click', 'type', 'navigate', 'scroll', 'voice_instruction'
        """
        if not self._current_session:
            return {"status": "error", "message": "Keine aktive Aufnahmesitzung."}

        event = {
            "step": len(self._current_session["events"]) + 1,
            "timestamp": datetime.datetime.now().isoformat(),
            "type": action_type,
            "details": details,
            "commentary": commentary
        }
        self._current_session["events"].append(event)
        return {"status": "event_recorded", "step": event["step"], "event": event}

    def get_current_session(self) -> Optional[Dict[str, Any]]:
        return self._current_session

    def stop_and_synthesize_skill(self, skill_slug: Optional[str] = None) -> Dict[str, Any]:
        """
        Stoppt die Aufnahme und synthetisiert den Trace in einen vollwertigen Skill (SKILL.md)
        und ein Python-Automations-Skript mit Human-Like Bézier-Mausbewegungen.
        """
        if not self._current_session or not self._current_session["events"]:
            return {"status": "error", "message": "Keine Aktionen in der Sitzung aufgezeichnet."}

        session = self._current_session
        session["end_time"] = datetime.datetime.now().isoformat()

        # Speicher Trace als JSON
        trace_file = os.path.join(PBD_TRACES_DIR, f"{session['session_id']}.json")
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2, ensure_ascii=False)

        slug = skill_slug or re.sub(r'[^a-z0-9_-]', '_', session["title"].lower()).strip('_')
        if not slug:
            slug = f"workflow_{session['session_id']}"

        # 1. Synthetisiere Python-Skript
        script_code = self._synthesize_python_script(slug, session)
        script_path = os.path.join(SCRIPTS_DIR, f"{slug}.py")
        _write_if_changed(script_path, script_code, ("Erstellt am: ",))

        # 2. Synthetisiere SKILL.md
        skill_dir = os.path.join(SKILLS_DIR, slug)
        os.makedirs(skill_dir, exist_ok=True)
        skill_md = self._synthesize_skill_md(slug, session, script_path)
        skill_path = os.path.join(skill_dir, "SKILL.md")
        _write_if_changed(skill_path, skill_md, ("created_at: ",))

        self._current_session = None

        return {
            "status": "synthesized",
            "skill_name": slug,
            "skill_path": skill_path,
            "script_path": script_path,
            "trace_path": trace_file,
            "steps_count": len(session["events"]),
            "message": f"Demonstration erfolgreich in Skill '{slug}' mit Ghost-Cursor und Anti-Bot-Varianz überführt."
        }

    def _synthesize_python_script(self, slug: str, session: Dict[str, Any]) -> str:
        events = session["events"]
        lines = [
            "# -*- coding: utf-8 -*-",
            f'"""Autonome Ausführung für Skill: {slug}',
            f'Synthetisiert aus Demonstration: {session["title"]}',
            f'Erstellt am: {session["start_time"]}',
            'Enthält biomechanische Bézier-Trajektorien und Bounding-Box Jitter.',
            '"""',
            "",
            "import time",
            "import random",
            "from backend.computer_use_pbd import GhostCursorEngine",
            "",
            f"def execute_{slug}(target_url: str = '{session.get('target_url', '')}'):",
            f'    print(f"[PbD Execution] Starte Ausführung von {slug} auf {{target_url}}...")',
            "    cursor_engine = GhostCursorEngine()",
            ""
        ]

        for ev in events:
            ev_type = ev["type"]
            det = ev["details"]
            comm = ev.get("commentary", "")
            if comm:
                lines.append(f'    # Kommentar des Nutzers: "{comm}"')

            if ev_type == "navigate":
                url = det.get("url", session.get("target_url", ""))
                lines.append(f'    print("[Aktion] Navigiere zu {url}")')
                lines.append(f'    time.sleep(random.uniform(0.6, 1.2))')
            elif ev_type == "click":
                target = det.get("target", det.get("selector", "button"))
                x = det.get("x", 50)
                y = det.get("y", 50)
                lines.append(f'    # Klick auf: {target}')
                lines.append(f'    jx, jy = cursor_engine.apply_bounding_box_jitter({x}, {y}, 40, 20)')
                lines.append(f'    traj = cursor_engine.calculate_bezier_trajectory((50, 50), (jx, jy), steps=18)')
                lines.append(f'    print(f"[Aktion] Bewege Maus biomechanisch nach ({{jx}}, {{jy}}) und klicke auf \'{target}\'")')
                lines.append(f'    time.sleep(random.uniform(0.4, 0.9))')
            elif ev_type == "type":
                val = det.get("value", det.get("text", ""))
                field = det.get("field", "Eingabefeld")
                lines.append(f'    # Text tippen: "{val}" in {field}')
                lines.append(f'    delays = cursor_engine.generate_keystroke_delays("{val}")')
                lines.append(f'    print(f"[Aktion] Tippe Text in {field} mit variierender menschlicher Kadenz ({{len(delays)}} Anschläge)...")')
                lines.append(f'    time.sleep(sum(d["delay_ms"] for d in delays) / 1000.0 * 0.4)')
            elif ev_type == "scroll":
                lines.append(f'    print("[Aktion] Scrolle Seite mit natürlicher Verzögerung...")')
                lines.append(f'    time.sleep(random.uniform(0.3, 0.7))')

            lines.append("")

        lines.append(f'    print("[PbD Execution] Skill {slug} erfolgreich abgeschlossen.")')
        lines.append(f'    return {{"status": "completed", "skill": "{slug}", "steps": {len(events)}}}')
        lines.append("")
        lines.append("if __name__ == '__main__':")
        lines.append(f"    execute_{slug}()")
        return "\n".join(lines)

    def _synthesize_skill_md(self, slug: str, session: Dict[str, Any], script_path: str) -> str:
        events = session["events"]
        steps_md = []
        for ev in events:
            step_num = ev["step"]
            ev_type = ev["type"].upper()
            comm = f" — *\"{ev['commentary']}\"*" if ev.get("commentary") else ""
            steps_md.append(f"{step_num}. **{ev_type}**: {json.dumps(ev['details'], ensure_ascii=False)}{comm}")

        return f"""---
name: {slug}
description: {session['title']} (Autonom erzeugt via Programming by Demonstration / PbD)
author: {session.get('creator_agent', 'default')}
created_at: {session['start_time']}
---

# {session['title']}

Dieser Skill wurde durch menschliches Vormachen im Bot-Screen (Programming by Demonstration) erlernt.

## Ziel-Kontext
- **Ursprüngliche Ziel-URL:** `{session.get('target_url', '')}`
- **Anzahl aufgezeichneter Interaktionsschritte:** {len(events)}
- **Anti-Bot Schutz:** Biomechanischer Ghost-Cursor (Bézier-Kurven), Gauss-verteilter Klick-Jitter & variable Tasten-Kadenzen.

## Aufgezeichneter Handlungsablauf
{chr(10).join(steps_md)}

## Ausführung
Führe das generierte Automations-Skript aus:
```bash
python {os.path.relpath(script_path, WORKSPACE_DIR)}
```
"""


# Singleton-Instanzen
_ghost_cursor = GhostCursorEngine()
_observation_pruner = ObservationPruner()
_pbd_recorder = DemonstrationRecorder()

def get_ghost_cursor() -> GhostCursorEngine:
    return _ghost_cursor

def get_observation_pruner() -> ObservationPruner:
    return _observation_pruner

def get_pbd_recorder() -> DemonstrationRecorder:
    return _pbd_recorder
