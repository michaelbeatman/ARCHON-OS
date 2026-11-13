"""Konfigurierbares Modell-Routing pro Aufgabentyp.

Der Eigentümer entscheidet, welches Modell eine Aufgabe bekommt — nicht der
Orchestrator. Die Tabelle liegt in data/model_routing.json und ist über
Einstellungen → Provider & Gateway editierbar (Zeilen hinzufügen, Provider und
Modell wählen).

Zusätzlich enthält die Datei die Autonomie-Stufen für Operations und den
Orchestrator:
  manual      = schlägt nur vor, führt nichts aus
  approval    = handelt erst nach Freigabe (HITL)
  autonomous  = handelt selbstständig im erlaubten Rahmen

Der Resolver ist bewusst konservativ: unbekannter Aufgabentyp -> Default-Modell
des Profils, niemals ein stiller Fallback auf ein fremdes Modell.
"""

from __future__ import annotations

import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "data", "model_routing.json")
_LOCK = threading.Lock()

AUTONOMY_LEVELS = ("manual", "approval", "autonomous")

DEFAULT_ROUTES = [
    {"task": "code", "label": "Code / Engineering", "provider": "openrouter", "model": "deepseek/deepseek-chat"},
    {"task": "reasoning", "label": "Strategie / Reasoning", "provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    {"task": "vision", "label": "Vision / OCR", "provider": "openrouter", "model": "nvidia/nemotron-3.5-super-vl:free"},
    {"task": "writing", "label": "Texte / Content", "provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    {"task": "triage", "label": "Triage / kurze Antworten", "provider": "openrouter", "model": "cohere/north-mini-code:free"},
    {"task": "background", "label": "Hintergrund / Bulk", "provider": "openrouter", "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"},
]

DEFAULT_CONFIG = {
    "enabled": False,
    "routes": DEFAULT_ROUTES,
    "autonomy": {"operations": "approval", "orchestrator": "approval"},
}


def _normalize_route(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    task = str(item.get("task") or "").strip().lower()
    model = str(item.get("model") or "").strip()
    if not task or not model:
        return None
    return {
        "task": task,
        "label": str(item.get("label") or task).strip(),
        "provider": str(item.get("provider") or "openrouter").strip().lower(),
        "model": model,
    }


def load_config() -> dict:
    with _LOCK:
        if not os.path.exists(CONFIG_PATH):
            return json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            return json.loads(json.dumps(DEFAULT_CONFIG))

    cfg = {
        "enabled": bool(data.get("enabled", False)),
        "routes": [],
        "autonomy": {"operations": "approval", "orchestrator": "approval"},
    }
    for item in data.get("routes", []):
        norm = _normalize_route(item)
        if norm:
            cfg["routes"].append(norm)
    if not cfg["routes"]:
        cfg["routes"] = json.loads(json.dumps(DEFAULT_ROUTES))

    autonomy = data.get("autonomy") or {}
    for key in ("operations", "orchestrator"):
        level = str(autonomy.get(key, "approval")).strip().lower()
        cfg["autonomy"][key] = level if level in AUTONOMY_LEVELS else "approval"
    return cfg


def save_config(payload: dict) -> dict:
    """Validiert und speichert. Unbekannte Tasks werden übernommen, Duplikate abgelehnt."""
    routes = []
    seen = set()
    for item in (payload or {}).get("routes", []):
        norm = _normalize_route(item)
        if not norm:
            continue
        if norm["task"] in seen:
            raise ValueError(f"Doppelter Aufgabentyp: {norm['task']}")
        seen.add(norm["task"])
        routes.append(norm)
    if not routes:
        raise ValueError("Mindestens eine Route erforderlich.")

    autonomy = (payload or {}).get("autonomy") or {}
    clean_autonomy = {}
    for key in ("operations", "orchestrator"):
        level = str(autonomy.get(key, "approval")).strip().lower()
        if level not in AUTONOMY_LEVELS:
            raise ValueError(f"Ungültige Autonomie-Stufe für {key}: {level}")
        clean_autonomy[key] = level

    cfg = {
        "enabled": bool((payload or {}).get("enabled", False)),
        "routes": routes,
        "autonomy": clean_autonomy,
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with _LOCK:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    return cfg


def resolve(task: str) -> dict | None:
    """Liefert die konfigurierte Route für einen Aufgabentyp (oder None)."""
    cfg = load_config()
    key = str(task or "").strip().lower()
    for route in cfg["routes"]:
        if route["task"] == key:
            return dict(route)
    return None


_TASK_HINTS = {
    "code": ("code", "python", "javascript", "typescript", "bug", "refactor", "api", "sql", "docker", "deploy", "script"),
    "vision": ("screenshot", "bild", "image", "ocr", "scan", "vision", "photo", "grafik"),
    "writing": ("text", "artikel", "copy", "blog", "newsletter", "post", "story", "übersetzung", "translation"),
    "triage": ("kurz", "triage", "einordnen", "priorisieren", "klassifizieren"),
    "background": ("hintergrund", "bulk", "batch", "stapel", "routine"),
}


def classify_task(text: str) -> str:
    """Ordnet einen Aufgabentext einer Kategorie zu. Konservativ: Default 'reasoning'."""
    low = (text or "").lower()
    scores = {task: sum(1 for kw in kws if kw in low) for task, kws in _TASK_HINTS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "reasoning"


def autonomy_level(scope: str = "orchestrator") -> str:
    cfg = load_config()
    return cfg["autonomy"].get(scope, "approval")


def is_enabled() -> bool:
    return bool(load_config().get("enabled", False))
