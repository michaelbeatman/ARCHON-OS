# -*- coding: utf-8 -*-
"""
scripts/test_pbd_computer_use.py
================================
Validiert die Kern-Funktionalitäten von Meilenstein 26:
1. GhostCursorEngine (Bézier-Kurven, Bounding-Box Jitter, Tastenanschlag-Kadenzen)
2. ObservationPruner (HTML a11y Pruning & Token-Reduktion)
3. DemonstrationRecorder & PbDSynthesizer (Programming by Demonstration -> SKILL.md & Script)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.computer_use_pbd import (
    GhostCursorEngine,
    ObservationPruner,
    DemonstrationRecorder
)

def test_ghost_cursor():
    print("--- [TEST 1] GhostCursorEngine (Biomechanik & Jitter) ---")
    engine = GhostCursorEngine()

    # 1. Trajektorie
    traj = engine.calculate_bezier_trajectory((10.0, 20.0), (80.0, 75.0), steps=20)
    assert len(traj) == 21, f"Erwartet 21 Punkte, erhalten: {len(traj)}"
    assert traj[0]["step"] == 0
    assert traj[-1]["step"] == 20
    print(f"✓ Bézier-Pfade erfolgreich berechnet: {len(traj)} Stützpunkte von (10, 20) nach (80, 75).")

    # 2. Bounding Box Jitter
    center_x, center_y = 50.0, 50.0
    jittered_points = [engine.apply_bounding_box_jitter(center_x, center_y, width=40.0, height=20.0) for _ in range(5)]
    unique_points = set(jittered_points)
    assert len(unique_points) > 1, "Jitter liefert identische Punkte!"
    print(f"✓ Gaussian Bounding-Box Jitter aktiv: Stichproben: {jittered_points[:2]}")

    # 3. Tastenanschläge
    delays = engine.generate_keystroke_delays("Senior Python Engineer!")
    assert len(delays) == len("Senior Python Engineer!")
    avg_delay = sum(d["delay_ms"] for d in delays) / len(delays)
    print(f"✓ Menschliche Tastatur-Kadenz: {len(delays)} Anschläge mit Ø {avg_delay:.1f}ms Delay.")


def test_observation_pruner():
    print("\n--- [TEST 2] ObservationPruner (a11y Tree & Token-Einsparung) ---")
    pruner = ObservationPruner()

    dummy_html = """
    <html>
      <head>
        <style>body { font-family: sans-serif; } .header { background: red; }</style>
        <script>function trackUser() { fetch('/analytics'); }</script>
      </head>
      <body>
        <div class="container wrapper main-page">
          <svg width="100" height="100"><circle cx="50" cy="50" r="40" stroke="green" stroke-width="4" fill="yellow" /></svg>
          <header>
            <a href="/jobs">Jobs & Karriere</a>
            <a href="/login">Anmelden</a>
          </header>
          <main>
            <input type="text" placeholder="Jobtitel oder Stichwort suchen..." />
            <input type="hidden" name="csrf" value="98723498" />
            <button class="btn btn-primary">Bewerbung absenden</button>
            <button class="btn btn-secondary">Filter zurücksetzen</button>
          </main>
        </div>
      </body>
    </html>
    """

    res = pruner.prune_html_to_a11y_tree(dummy_html)
    assert res["elements_count"] >= 4, f"Erwartet mindestens 4 interaktive Elemente, erhalten: {res['elements_count']}"
    assert res["token_reduction_percent"] > 50.0, f"Token-Reduktion zu gering: {res['token_reduction_percent']}%"
    print(f"✓ a11y Pruning erfolgreich: {res['elements_count']} interaktive Elemente extrahiert.")
    print(f"✓ Token-Reduktion: {res['raw_characters']} Zeichen -> {res['pruned_characters']} Zeichen ({res['token_reduction_percent']}% Einsparung).")
    print("Auszug des semantischen a11y-Trees:")
    for line in res["pruned_a11y_tree"].splitlines()[:4]:
        print(f"   {line}")


def test_pbd_recording_and_synthesis():
    print("\n--- [TEST 3] PbD Demonstration & Skill-Synthese ---")
    recorder = DemonstrationRecorder()

    # 1. Start
    start_res = recorder.start_recording(
        session_title="Bewerbungen Prüfen und Senior Coder Selektieren",
        target_url="https://karriere.portal.internal",
        creator_agent="recruiter_specialist"
    )
    assert start_res["status"] == "recording_started"
    print(f"✓ PbD-Aufnahme gestartet: Session-ID {start_res['session_id']}")

    # 2. Events aufzeichnen
    recorder.record_event("navigate", {"url": "https://karriere.portal.internal"}, commentary="Navigiere zum Karriereportal")
    recorder.record_event("click", {"selector": "#btn-filter-senior", "x": 65, "y": 42}, commentary="Klicke auf Filter für Senior-Profile")
    recorder.record_event("type", {"field": "Suche", "text": "Python Fullstack"}, commentary="Tippe Suchbegriff mit natürlicher Kadenz")
    recorder.record_event("click", {"selector": "#btn-submit-review", "x": 80, "y": 70}, commentary="Bewerbungen freigeben")

    session = recorder.get_current_session()
    assert len(session["events"]) == 4, f"Erwartet 4 Events, erhalten: {len(session['events'])}"
    print(f"✓ 4 Interaktionsschritte erfolgreich mit Sprachkommentaren protokolliert.")

    # 3. Stop & Synthese
    synth_res = recorder.stop_and_synthesize_skill(skill_slug="auto_senior_applicant_screener")
    assert synth_res["status"] == "synthesized"
    assert os.path.exists(synth_res["skill_path"])
    assert os.path.exists(synth_res["script_path"])
    print(f"✓ Skill erfolgreich synthetisiert:")
    print(f"   - Skill Manifest: {synth_res['skill_path']}")
    print(f"   - Python Automation: {synth_res['script_path']}")


if __name__ == "__main__":
    test_ghost_cursor()
    test_observation_pruner()
    test_pbd_recording_and_synthesis()
    print("\n🎉 ALLE TESTS FÜR MEILENSTEIN 26 (Autonomous Computer-Use & PbD) ERFOLGREICH!")
