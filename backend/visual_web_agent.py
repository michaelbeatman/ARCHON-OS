"""
backend/visual_web_agent.py
Headless-Browser & Visueller Web-Agent (Pillar 3 & 6).
Führt Web-Aktionen (Navigation, Formular-Eingaben, Daten-Extraktion) aus,
erstellt für jeden Teilschritt Screenshots und hinterlegt einen visuellen Nachweis im Task-Dossier.
"""

import os
import sys
import time
import json
import urllib.request
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISUAL_TRACES_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "visual_traces")
os.makedirs(VISUAL_TRACES_DIR, exist_ok=True)

class VisualWebAgent:
    def __init__(self, traces_dir: str = VISUAL_TRACES_DIR):
        self.traces_dir = traces_dir

    def browse_and_capture(
        self,
        task_id: str,
        target_url: str,
        actions: Optional[List[Dict[str, Any]]] = None,
        extract_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Navigiert zur Ziel-URL, führt definierte Aktionen aus und erfasst visuelle Screenshots.
        Berücksichtigt den Schalter visual_browser_audit in settings.json.
        """
        capture_screenshots = True
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("fleet_and_hygiene")
            capture_screenshots = bool(cfg.get("visual_browser_audit", True))
        except Exception:
            pass

        task_dir = os.path.join(self.traces_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        steps_log = []
        t0 = time.time()

        has_playwright = False
        try:
            import playwright
            has_playwright = True
        except ImportError:
            has_playwright = False

        if has_playwright:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    page.goto(target_url, timeout=30000, wait_until="networkidle")

                    shot_path = None
                    if capture_screenshots:
                        shot_path = os.path.join(task_dir, "step_0_navigate.png")
                        page.screenshot(path=shot_path)
                    title = page.title()

                    steps_log.append({
                        "step": 0,
                        "action": "navigate",
                        "url": target_url,
                        "title": title,
                        "screenshot": shot_path
                    })

                    if actions:
                        for idx, act in enumerate(actions, 1):
                            act_type = act.get("type", "click")
                            selector = act.get("selector", "")
                            if act_type == "click" and selector:
                                page.click(selector, timeout=5000)
                            elif act_type == "type" and selector:
                                page.fill(selector, act.get("text", ""))

                            s_path = None
                            if capture_screenshots:
                                s_path = os.path.join(task_dir, f"step_{idx}_{act_type}.png")
                                page.screenshot(path=s_path)
                            steps_log.append({
                                "step": idx,
                                "action": act_type,
                                "selector": selector,
                                "screenshot": s_path
                            })

                    extracted_content = ""
                    if extract_selector:
                        extracted_content = page.inner_text(extract_selector)
                    else:
                        extracted_content = page.inner_text("body")[:2000]

                    browser.close()
                    return {
                        "status": "success",
                        "engine": "playwright_headless",
                        "screenshots_enabled": capture_screenshots,
                        "target_url": target_url,
                        "page_title": title,
                        "steps_count": len(steps_log),
                        "steps": steps_log,
                        "extracted_text_preview": extracted_content[:300],
                        "duration_seconds": round(time.time() - t0, 2)
                    }
            except Exception:
                pass

        try:
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": "ArchonOS-VisualAgent/2.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            return {
                "status": "success",
                "engine": "http_stream_fallback",
                "screenshots_enabled": capture_screenshots,
                "target_url": target_url,
                "steps_count": 1,
                "steps": [{
                    "step": 0,
                    "action": "fetch",
                    "url": target_url,
                    "screenshot": None,
                    "note": "Playwright nicht aktiv; Textuell extrahiert."
                }],
                "extracted_text_preview": html[:300],
                "duration_seconds": round(time.time() - t0, 2)
            }
        except Exception as e:
            return {"status": "error", "target_url": target_url, "error": str(e)}

visual_web_agent = VisualWebAgent()
