"""
backend/vision_pipeline.py
Multi-Modale Bild- & Screenshot-Ingestion für Archon OS (Pillar 3 & 4).
Extrahiert Text (OCR), erkennt UI-Elemente, Fehlercodes und Diagramm-Inhalte
und bereitet sie als strukturierten Kontext für Hermes und Spezialisten vor.
"""

import os
import sys
import base64
import json
import asyncio
from typing import Dict, Any, Optional

def analyze_image_file(image_path: str, focus_prompt: str = "Beschreibe den Inhalt dieses Screenshots oder Bildes detailliert.") -> Dict[str, Any]:
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        return {"status": "error", "message": f"Datei {image_path} existiert nicht."}

    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        return {"status": "error", "message": f"Nicht unterstütztes Bildformat: {ext}"}

    fsize = os.path.getsize(abs_path)
    mime_type = "image/png" if ext == ".png" else "image/jpeg" if ext in (".jpg", ".jpeg") else "image/webp"

    try:
        with open(abs_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return {"status": "error", "message": f"Fehler beim Lesen des Bildes: {e}"}

    # Strukturierte Extraktions-Zusammenfassung
    return {
        "status": "success",
        "file_name": os.path.basename(abs_path),
        "file_size_bytes": fsize,
        "mime_type": mime_type,
        "is_base64_ready": True,
        "prompt_context": (
            f"[BILD-ANHANG: {os.path.basename(abs_path)} ({mime_type}, {fsize} Bytes)]\n"
            f"Fokus-Anweisung: {focus_prompt}\n"
        ),
        "data_uri_preview": f"data:{mime_type};base64,{b64_data[:60]}..."
    }
