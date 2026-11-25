# -*- coding: utf-8 -*-
"""
backend/workflow_node_plugins.py
================================
Standardisierte "VST"-artige Node-Plugin-Schnittstelle fuer Archon OS Workflows.

Jeder Baustein deklariert:
- `plugin_id`, `label`, `category`, `icon`, `description`
- `adapter`: "local" | "mcp" | "http"
- `params_schema`: typisierte Parameter-Liste (select, text, textarea, number, checkbox, path)
- `outputs_schema`: erwartete Ausgabe-Felder fuer nachgelagerte {{upstream.<node>.<field>}}-Referenzen

Eigene & 3rd-Party-Plugins koennen zudem deklarativ als JSON-Dateien unter
`plugins/workflow_nodes/*.json` abgelegt werden und erscheinen automatisch
in der Workflow-Studio-Palette.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("archon.workflow_node_plugins")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_NODES_DIR = os.path.join(WORKSPACE_DIR, "plugins", "workflow_nodes")

PluginHandler = Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


def _showroom_media_dir(node: Dict[str, Any], subdir: str = "02_Medien") -> str:
    try:
        from archon.core.paths import PROJEKTE_DIR
        base = PROJEKTE_DIR
    except Exception:
        base = os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE")
    wf_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("workflow_id") or "workflow_media")).strip("_")[:48] or "workflow_media"
    target = os.path.join(base, f"WF_{wf_slug}", subdir)
    os.makedirs(target, exist_ok=True)
    return target


def _safe_media_input_path(raw_path: str) -> str:
    """Prueft Eingabepfade auf Traversal und begrenzt auf erlaubte Workspace-/Datenpfade."""
    p = str(raw_path or "").strip()
    if not p:
        return ""
    from utils.path_jail import safe_path_within
    roots = [WORKSPACE_DIR, "/opt/data", "/projects"]
    try:
        from archon.core.paths import PROJEKTE_DIR
        roots.append(os.path.dirname(PROJEKTE_DIR))
    except Exception:
        pass
    return safe_path_within(p, roots, allow_dirs=False)


def resolve_upstream_templates(params: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    """Loest {{upstream.<node_id>.<field>}} und {{upstream.<field>}} in Plugin-Parametern auf."""
    if not isinstance(params, dict):
        return {}
    up = upstream if isinstance(upstream, dict) else {}

    def _lookup(expr: str) -> Optional[str]:
        parts = [x.strip() for x in expr.split(".") if x.strip()]
        if not parts or parts[0] != "upstream":
            return None
        if len(parts) == 2:
            key = parts[1]
            for val in up.values():
                if isinstance(val, dict) and key in val and val[key] is not None:
                    return str(val[key])
        if len(parts) >= 3:
            node_id = parts[1]
            cur: Any = up.get(node_id)
            for k in parts[2:]:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    cur = None
                    break
            if cur is not None:
                return str(cur)
        return None

    def _subst(val: Any) -> Any:
        if isinstance(val, str):
            return re.sub(
                r"\{\{\s*(upstream\.[a-zA-Z0-9_.-]+)\s*\}\}",
                lambda m: _lookup(m.group(1)) if _lookup(m.group(1)) is not None else m.group(0),  # type: ignore[arg-type, return-value]
                val,
            )
        if isinstance(val, list):
            return [_subst(x) for x in val]
        if isinstance(val, dict):
            return {k: _subst(v) for k, v in val.items()}
        return val

    return _subst(params)


# =====================================================================
# EINGEBAUTE CORE MEDIA & 3RD-PARTY NODE-PLUGINS
# =====================================================================

CORE_NODE_PLUGINS: Dict[str, Dict[str, Any]] = {
    "ffmpeg": {
        "plugin_id": "ffmpeg",
        "label": "FFmpeg Video/Audio",
        "category": "video",
        "icon": "🎬",
        "adapter": "local",
        "description": "Schneidet, konvertiert, skaliert (9:16 / 16:9), brennt Untertitel/Watermarks ein und extrahiert Audio.",
        "outputs_schema": ["video_path", "audio_path", "thumbnail_path", "command", "content"],
        "params_schema": [
            {"key": "mode", "label": "Modus", "type": "select", "default": "clip_cut", "options": ["clip_cut", "aspect_9_16", "burn_subtitles", "extract_audio", "thumbnail_frame", "speed_ramp"], "group": "Schnitt"},
            {"key": "input_path", "label": "Eingabe-Datei ({{upstream.step_1.video_path}})", "type": "text", "default": "", "placeholder": "/opt/data/obsidian/.../input.mp4", "group": "Schnitt", "context_ref": True},
            {"key": "start_sec", "label": "Start (Sekunden)", "type": "number", "default": 0, "min": 0, "max": 86400, "step": 0.5, "group": "Schnitt"},
            {"key": "duration_sec", "label": "Dauer (Sekunden, 0 = voll)", "type": "number", "default": 30, "min": 0, "max": 3600, "step": 0.5, "group": "Schnitt"},
            {"key": "aspect_ratio", "label": "Seitenverhaeltnis", "type": "select", "default": "9:16", "options": ["9:16", "16:9", "1:1", "4:5", "original"], "group": "Format"},
            {"key": "resolution", "label": "Ziel-Aufloesung", "type": "select", "default": "1080x1920", "options": ["1080x1920", "1920x1080", "1080x1080", "1080x1350", "original"], "group": "Format"},
            {"key": "fps", "label": "FPS", "type": "select", "default": "30", "options": ["24", "25", "30", "60", "original"], "group": "Encode", "advanced": True},
            {"key": "crf", "label": "Qualitaet (CRF 16-30)", "type": "number", "default": 21, "min": 14, "max": 35, "step": 1, "group": "Encode", "advanced": True, "help": "Niedriger = bessere Qualitaet, langsamere Kodierung."},
            {"key": "video_codec", "label": "Video-Codec", "type": "select", "default": "libx264", "options": ["libx264", "libx265", "copy"], "group": "Encode", "advanced": True},
            {"key": "audio_codec", "label": "Audio-Codec", "type": "select", "default": "aac", "options": ["aac", "mp3", "copy", "none"], "group": "Audio", "advanced": True},
            {"key": "audio_bitrate", "label": "Audio-Bitrate", "type": "select", "default": "192k", "options": ["128k", "192k", "256k", "320k"], "group": "Audio", "advanced": True},
            {"key": "subtitle_path", "label": "Untertitel (.srt/.ass, optional)", "type": "text", "default": "", "placeholder": "{{upstream.step_1.srt_path}}", "group": "Overlay", "advanced": True, "context_ref": True},
            {"key": "watermark_text", "label": "Watermark-Text (optional)", "type": "text", "default": "", "placeholder": "@archon_os", "group": "Overlay", "advanced": True},
            {"key": "output_format", "label": "Ausgabe-Format", "type": "select", "default": "mp4", "options": ["mp4", "mov", "webm", "mp3", "jpg"], "group": "Format", "advanced": True},
            {"key": "dry_run", "label": "Nur Befehl planen (Dry-Run)", "type": "checkbox", "default": False, "group": "Schnitt", "advanced": True},
        ],
    },
    "kinocut": {
        "plugin_id": "kinocut",
        "label": "KinoCut AI Repurpose",
        "category": "video",
        "icon": "✂️",
        "adapter": "mcp",
        "description": "Erstellt aus Langform-Skripten oder Videos plattformfertige Kurz-Clips (Shorts, Reels, LinkedIn).",
        "outputs_schema": ["clips", "clip_count", "video_path", "content"],
        "params_schema": [
            {"key": "source_video", "label": "Quell-Video (optional)", "type": "text", "default": "", "placeholder": "/opt/data/inbox/raw.mp4"},
            {"key": "target_platform", "label": "Ziel-Plattform", "type": "select", "default": "youtube_shorts", "options": ["youtube_shorts", "linkedin", "tiktok", "instagram_reels"]},
            {"key": "clip_count", "label": "Anzahl Clips", "type": "number", "default": 3, "min": 1, "max": 12, "step": 1},
            {"key": "min_duration_sec", "label": "Min. Clip-Laenge (s)", "type": "number", "default": 20, "min": 5, "max": 180, "step": 5},
            {"key": "max_duration_sec", "label": "Max. Clip-Laenge (s)", "type": "number", "default": 58, "min": 10, "max": 300, "step": 5},
            {"key": "aspect_ratio", "label": "Format", "type": "select", "default": "9:16", "options": ["9:16", "16:9", "1:1"]},
            {"key": "hook_focus", "label": "Hook-Fokus", "type": "select", "default": "high_retention", "options": ["high_retention", "contrarian", "storytelling", "how_to"]},
            {"key": "burn_captions", "label": "Dynamische Untertitel einbrennen", "type": "checkbox", "default": True},
            {"key": "caption_style", "label": "Untertitel-Stil", "type": "select", "default": "hormozi_bold", "options": ["hormozi_bold", "clean_minimal", "subtitle_box"]},
            {"key": "dry_run", "label": "Dry-Run (nur Clip-Manifest)", "type": "checkbox", "default": False},
        ],
    },
    "tts": {
        "plugin_id": "tts",
        "label": "Voice / Edge-TTS",
        "category": "audio",
        "icon": "🎙️",
        "adapter": "local",
        "description": "Erzeugt naturgetreue Sprachausgabe (MP3/WAV) direkt ueber edge-tts fuer Videos, Reels & Podcasts.",
        "outputs_schema": ["audio_path", "voice", "content"],
        "params_schema": [
            {"key": "text", "label": "Sprechtext (leer = Upstream-Content)", "type": "textarea", "default": "", "placeholder": "{{upstream.step_1.content}}"},
            {"key": "voice", "label": "Stimme", "type": "select", "default": "de-DE-ConradNeural", "options": ["de-DE-ConradNeural", "de-DE-KatjaNeural", "de-AT-JonasNeural", "en-US-AndrewNeural", "en-US-AvaNeural", "en-GB-RyanNeural"]},
            {"key": "rate", "label": "Sprechtempo", "type": "select", "default": "+0%", "options": ["-20%", "-10%", "+0%", "+10%", "+20%"]},
            {"key": "pitch", "label": "Tonhoehe", "type": "select", "default": "+0Hz", "options": ["-10Hz", "-5Hz", "+0Hz", "+5Hz", "+10Hz"]},
            {"key": "output_format", "label": "Audio-Format", "type": "select", "default": "mp3", "options": ["mp3", "wav"]},
            {"key": "filename_prefix", "label": "Dateipraefix", "type": "text", "default": "voiceover"},
        ],
    },
    "suno": {
        "plugin_id": "suno",
        "label": "Suno Music & Jingle",
        "category": "audio",
        "icon": "🎵",
        "adapter": "http",
        "description": "3rd-Party-Adapter fuer Suno AI Musik-/Jingle-Generierung (API-Key via SUNO_API_KEY / Plugin-Config).",
        "outputs_schema": ["audio_path", "track_url", "title", "content"],
        "params_schema": [
            {"key": "title", "label": "Track-Titel", "type": "text", "default": "Archon Intro Track"},
            {"key": "prompt", "label": "Musik-Prompt / Lyrics", "type": "textarea", "default": "", "placeholder": "Energetic modern synthwave intro for tech podcast"},
            {"key": "style_tags", "label": "Style-Tags", "type": "text", "default": "synthwave, ambient, crisp, 120bpm"},
            {"key": "instrumental", "label": "Rein Instrumental (ohne Gesang)", "type": "checkbox", "default": True},
            {"key": "duration_sec", "label": "Ziel-Dauer (Sekunden)", "type": "number", "default": 30, "min": 10, "max": 240, "step": 5},
            {"key": "model_version", "label": "Suno-Modell", "type": "select", "default": "v4", "options": ["v4", "v3.5", "v3"]},
            {"key": "api_endpoint", "label": "Suno-kompatibler API-Endpoint", "type": "text", "default": "", "placeholder": "https://api.suno-provider.example/v1/generate"},
        ],
    },
    "image_gen": {
        "plugin_id": "image_gen",
        "label": "Bild & Thumbnail",
        "category": "design",
        "icon": "🖼️",
        "adapter": "local",
        "description": "Generiert Thumbnails, Social-Visuals und Cover-Grafiken (Zero-Egress-konform).",
        "outputs_schema": ["image_path", "prompt", "content"],
        "params_schema": [
            {"key": "prompt", "label": "Bild-Prompt (leer = aus Upstream)", "type": "textarea", "default": ""},
            {"key": "negative_prompt", "label": "Negative Prompt", "type": "text", "default": "blurry, watermark, low quality, text artifacts"},
            {"key": "aspect_ratio", "label": "Format", "type": "select", "default": "16:9", "options": ["16:9", "9:16", "1:1", "4:5"]},
            {"key": "style_preset", "label": "Stil-Preset", "type": "select", "default": "editorial_clean", "options": ["editorial_clean", "cinematic_dark", "minimal_tech", "photorealistic"]},
            {"key": "model", "label": "Bild-Modell (optional)", "type": "text", "default": ""},
            {"key": "save_to_showroom", "label": "Im Showroom (02_Medien) sichern", "type": "checkbox", "default": True},
        ],
    },
    "calendar_publish": {
        "plugin_id": "calendar_publish",
        "label": "Kalender & Publishing",
        "category": "business",
        "icon": "📅",
        "adapter": "local",
        "description": "Plant das freigegebene Deliverable im Operations-Kalender ein und verknuepft es mit dem Publishing-Kanal.",
        "outputs_schema": ["calendar_event_id", "scheduled_at", "channel", "content"],
        "params_schema": [
            {"key": "title", "label": "Kalender-Titel", "type": "text", "default": "Publishing: {{topic}}"},
            {"key": "channel", "label": "Publishing-Kanal", "type": "select", "default": "linkedin", "options": ["linkedin", "youtube", "tiktok", "newsletter", "blog"]},
            {"key": "auto_offset_hours", "label": "Vorlauf ab jetzt (Stunden)", "type": "number", "default": 24, "min": 1, "max": 720, "step": 1},
            {"key": "asset_path", "label": "Verknuepftes Media-Asset", "type": "text", "default": "", "placeholder": "{{upstream.step_1.video_path}}"},
            {"key": "n8n_webhook_action", "label": "n8n-Action (optional)", "type": "text", "default": "publish_linkedin"},
            {"key": "notes", "label": "Notizen / Beschreibung", "type": "textarea", "default": ""},
        ],
    },
}


def _load_third_party_node_plugins() -> Dict[str, Dict[str, Any]]:
    """Liest deklarative 3rd-Party-Node-Plugins aus plugins/workflow_nodes/*.json."""
    discovered: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(PLUGINS_NODES_DIR):
        return discovered
    for fname in sorted(os.listdir(PLUGINS_NODES_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(PLUGINS_NODES_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                spec = json.load(f)
            if not isinstance(spec, dict) or not spec.get("plugin_id"):
                continue
            pid = str(spec["plugin_id"]).strip().lower()
            spec["plugin_id"] = pid
            spec.setdefault("label", pid)
            spec.setdefault("category", "3rd_party")
            spec.setdefault("icon", "🔌")
            spec.setdefault("adapter", "http")
            spec.setdefault("params_schema", [])
            spec.setdefault("outputs_schema", ["content"])
            spec["third_party"] = True
            discovered[pid] = spec
        except Exception as exc:
            logger.warning(f"[NodePlugins] Fehler beim Laden von {fname}: {exc}")
    return discovered


def list_workflow_node_plugins() -> List[Dict[str, Any]]:
    """Liefert alle verfuegbaren Workflow-Node-Plugins (Core + 3rd-Party)."""
    merged = dict(CORE_NODE_PLUGINS)
    merged.update(_load_third_party_node_plugins())
    return list(merged.values())


def get_workflow_node_plugin(plugin_id: str) -> Optional[Dict[str, Any]]:
    pid = str(plugin_id or "").strip().lower()
    if not pid:
        return None
    if pid in CORE_NODE_PLUGINS:
        return CORE_NODE_PLUGINS[pid]
    return _load_third_party_node_plugins().get(pid)


def is_workflow_node_plugin(node_type: str) -> bool:
    return get_workflow_node_plugin(node_type) is not None


# =====================================================================
# KONFIGURATIONS-SCHEMA (Stations-Dialog, Drei-Spalten-Layout)
# =====================================================================

def get_plugin_schema(plugin_id: str) -> Dict[str, Any]:
    """Gibt das typisierte Parameter-Schema eines Bausteins fuer die UI zurueck."""
    plugin = get_workflow_node_plugin(plugin_id) or {}
    return {
        "plugin_id": plugin.get("plugin_id", str(plugin_id or "")),
        "label": plugin.get("label", str(plugin_id or "")),
        "category": plugin.get("category", ""),
        "fields": plugin.get("params_schema") or [],
        "outputs": plugin.get("outputs_schema") or [],
    }


def split_schema_fields(fields: List[Dict[str, Any]]) -> tuple:
    """Teilt Parameter in (primary, advanced, groups) fuer 'Add Optionen'."""
    primary: List[Dict[str, Any]] = []
    advanced: List[Dict[str, Any]] = []
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for field in fields or []:
        if not isinstance(field, dict) or not field.get("key"):
            continue
        group = str(field.get("group") or "Allgemein")
        groups.setdefault(group, []).append(field)
        (advanced if field.get("advanced") else primary).append(field)
    return primary, advanced, groups


def validate_node_config(plugin_id: str, overlay: Optional[Dict[str, Any]]) -> List[str]:
    """Validiert ein Config-Overlay gegen das Plugin-Schema (fail-closed)."""
    errors: List[str] = []
    fields = get_plugin_schema(plugin_id)["fields"]
    known = {f.get("key") for f in fields if isinstance(f, dict)}
    overlay = overlay if isinstance(overlay, dict) else {}
    for key in overlay:
        if key not in known:
            errors.append(f"Unbekannter Parameter: {key}")
    for field in fields:
        if not isinstance(field, dict):
            continue
        key = field.get("key")  # type: ignore[assignment]
        value = overlay.get(key, field.get("default"))
        ftype = str(field.get("type") or "text").lower()
        if ftype == "number":
            try:
                numeric = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                errors.append(f"{key}: keine Zahl")
                continue
            if field.get("min") is not None and numeric < float(field["min"]):
                errors.append(f"{key}: unterhalb Minimum {field['min']}")
            if field.get("max") is not None and numeric > float(field["max"]):
                errors.append(f"{key}: oberhalb Maximum {field['max']}")
        elif ftype == "select" and field.get("options"):
            if str(value) not in {str(o) for o in field["options"]}:
                errors.append(f"{key}: ungueltige Option {value!r}")
    return errors


def resolve_node_config(
    plugin_id: str,
    overlay: Optional[Dict[str, Any]] = None,
    upstream: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Plugin-Defaults + Overlay + {{upstream...}}-Templates, validiert."""
    errors = validate_node_config(plugin_id, overlay)
    if errors:
        raise ValueError("; ".join(errors))
    config: Dict[str, Any] = {}
    for field in get_plugin_schema(plugin_id)["fields"]:
        if isinstance(field, dict) and field.get("key"):
            config[field["key"]] = field.get("default")
    config.update(overlay or {})
    resolved = resolve_upstream_templates(config, upstream or {})
    # Kontext-Pakete: `ctx_<id>`-Referenzen zu den abgelegten Dateipfaden auflösen.
    try:
        from backend.context_packages import resolve_context_refs
        resolved = resolve_context_refs(resolved)
    except Exception as ctx_exc:
        logger.debug("[NodePlugins] Kontext-Referenzen nicht aufgelöst: %s", ctx_exc)
    return resolved


# =====================================================================
# AUSFUEHRUNGS-ADAPTER
# =====================================================================

async def _run_ffmpeg_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(params.get("mode") or "clip_cut")
    default_ext = "mp3" if mode == "extract_audio" else ("jpg" if mode == "thumbnail_frame" else "mp4")
    out_fmt = re.sub(r"[^a-z0-9]+", "", str(params.get("output_format") or default_ext).strip(".").lower()) or default_ext
    media_dir = _showroom_media_dir(node, "02_Medien")
    ts = time.strftime("%Y%m%d_%H%M%S")
    nonce = uuid.uuid4().hex[:6]
    out_file = os.path.join(media_dir, f"ffmpeg_{mode}_{ts}_{nonce}.{out_fmt}")

    raw_in = str(params.get("input_path") or "").strip()
    if not raw_in:
        for val in (upstream or {}).values():
            if isinstance(val, dict) and val.get("video_path"):
                raw_in = str(val["video_path"])
                break
    safe_in = raw_in if (bool(params.get("dry_run")) and raw_in) else (_safe_media_input_path(raw_in) if raw_in else "")

    cmd: List[str] = ["ffmpeg", "-y"]
    if safe_in:
        if float(params.get("start_sec") or 0) > 0:
            cmd += ["-ss", str(float(params["start_sec"]))]
        cmd += ["-i", safe_in]
        if float(params.get("duration_sec") or 0) > 0:
            cmd += ["-t", str(float(params["duration_sec"]))]

    if mode == "extract_audio":
        req_acodec = str(params.get("audio_codec") or "").strip().lower()
        if out_fmt == "mp3" and req_acodec in ("", "aac"):
            acodec_extract = "libmp3lame"
        elif out_fmt == "wav" and not req_acodec:
            acodec_extract = "pcm_s16le"
        else:
            acodec_extract = req_acodec or "libmp3lame"
        cmd += ["-vn", "-acodec", acodec_extract]
        if acodec_extract != "pcm_s16le":
            cmd += ["-b:a", str(params.get("audio_bitrate") or "192k")]
        cmd.append(out_file)
    elif mode == "thumbnail_frame":
        cmd += ["-vframes", "1", "-q:v", "2", out_file]
    else:
        vf_filters: List[str] = []
        aspect = str(params.get("aspect_ratio") or "9:16")
        res = str(params.get("resolution") or "1080x1920")
        if aspect == "9:16" and mode == "aspect_9_16":
            vf_filters.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0")
        if res != "original" and "x" in res:
            w, h = res.split("x", 1)
            vf_filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        sub_path = str(params.get("subtitle_path") or "").strip()
        if sub_path:
            safe_sub = _safe_media_input_path(sub_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            vf_filters.append(f"subtitles='{safe_sub}'")
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]
        if str(params.get("fps") or "30") != "original":
            cmd += ["-r", str(params["fps"])]
        vcodec = str(params.get("video_codec") or "libx264")
        acodec = str(params.get("audio_codec") or "aac")
        cmd += ["-c:v", vcodec]
        if vcodec in ("libx264", "libx265"):
            cmd += ["-crf", str(int(params.get("crf") or 21))]
        if acodec == "none":
            cmd += ["-an"]
        else:
            cmd += ["-c:a", acodec, "-b:a", str(params.get("audio_bitrate") or "192k")]
        cmd.append(out_file)

    cmd_str = " ".join(cmd)
    if bool(params.get("dry_run")) or not shutil.which("ffmpeg") or not safe_in:
        reason = "dry_run" if params.get("dry_run") else ("ffmpeg_binary_missing" if not shutil.which("ffmpeg") else "no_input_path")
        return {
            "status": "planned",
            "planned_only": True,
            "reason": reason,
            "command": cmd_str,
            "video_path": out_file if out_fmt not in ("mp3", "wav", "m4a", "aac", "jpg", "png") else "",
            "audio_path": out_file if out_fmt in ("mp3", "wav", "m4a", "aac") else "",
            "content": f"[FFmpeg ({reason})] Geplanter Befehl:\n`{cmd_str}`\nZiel: `{out_file}`",
        }

    try:
        proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "status": "error",
            "error": f"FFmpeg-Ausfuehrungsfehler: {exc}",
            "command": cmd_str,
            "content": "",
        }
    if proc.returncode != 0:
        return {
            "status": "error",
            "error": (proc.stderr or "FFmpeg fehlgeschlagen")[-600:],
            "command": cmd_str,
            "content": "",
        }
    return {
        "status": "success",
        "command": cmd_str,
        "video_path": out_file if out_fmt not in ("mp3", "wav", "m4a", "aac", "jpg", "png") else "",
        "audio_path": out_file if out_fmt in ("mp3", "wav", "m4a", "aac") else "",
        "thumbnail_path": out_file if out_fmt in ("jpg", "png") else "",
        "content": f"FFmpeg Render erfolgreich: `{out_file}`",
    }


async def _run_kinocut_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    from backend.content_machine import generate_video_clip_matrix
    up_texts = [
        str(v.get("content") or v.get("summary") or "")
        for v in (upstream or {}).values()
        if isinstance(v, dict)
    ]
    script_text = "\n\n".join(t for t in up_texts if t) or str(node.get("prompt") or node.get("title") or "KinoCut Clip")
    matrix = await generate_video_clip_matrix(
        campaign_id=str(node.get("workflow_id") or "wf_kinocut"),
        script_text=script_text,
        clip_count=int(params.get("clip_count") or 3),
        target_channels=[str(params.get("target_platform") or "youtube_shorts")],
        dry_run=bool(params.get("dry_run", False)),
    )
    rendered = json.dumps(matrix, ensure_ascii=False, indent=2)
    clips_list = matrix.get("clips") or matrix.get("clips_created") or []
    return {
        "status": "success",
        "clips": clips_list,
        "clip_count": len(clips_list),
        "media_matrix": matrix,
        "content": rendered,
    }


async def _run_tts_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    text = str(params.get("text") or "").strip()
    if not text:
        for val in (upstream or {}).values():
            if isinstance(val, dict) and (val.get("content") or val.get("summary")):
                text = str(val.get("content") or val.get("summary")).strip()
                break
    if not text:
        return {"status": "error", "error": "Kein Sprechtext fuer TTS vorhanden.", "content": ""}

    voice = str(params.get("voice") or "de-DE-ConradNeural")
    rate = str(params.get("rate") or "+0%")
    pitch = str(params.get("pitch") or "+0Hz")
    fmt = str(params.get("output_format") or "mp3").strip(".")
    prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(params.get("filename_prefix") or "voiceover")).strip("_") or "voiceover"
    media_dir = _showroom_media_dir(node, "02_Medien")
    out_file = os.path.join(media_dir, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.{fmt}")

    if not shutil.which("edge-tts"):
        return {
            "status": "planned",
            "planned_only": True,
            "reason": "edge_tts_binary_missing",
            "voice": voice,
            "audio_path": out_file,
            "content": f"[Edge-TTS Dry-Run] Voice `{voice}` ({rate}, {pitch}) -> `{out_file}` ({len(text)} Zeichen)",
        }

    cmd = [
        "edge-tts",
        "--voice", voice,
        "--rate", rate,
        "--pitch", pitch,
        "--text", text[:4500],
        "--write-media", out_file,
    ]
    proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        return {"status": "error", "error": (proc.stderr or "edge-tts fehlgeschlagen")[-500:], "content": ""}
    return {
        "status": "success",
        "audio_path": out_file,
        "voice": voice,
        "content": f"Audio generiert (`{voice}`): `{out_file}`",
    }


async def _run_suno_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    endpoint = str(params.get("api_endpoint") or os.environ.get("SUNO_API_ENDPOINT") or "").strip()
    api_key = str(os.environ.get("SUNO_API_KEY") or "").strip()
    if not endpoint or not api_key:
        return {
            "status": "planned",
            "planned_only": True,
            "reason": "suno_api_not_configured",
            "title": str(params.get("title") or "Track"),
            "content": (
                f"[Suno 3rd-Party Adapter] Bereit fuer '{params.get('title')}' "
                f"(Style: {params.get('style_tags')}, Instrumental: {params.get('instrumental')}, "
                f"Modell: {params.get('model_version')}). "
                "Hinterlege `SUNO_API_ENDPOINT` & `SUNO_API_KEY` fuer Live-Rendering."
            ),
        }

    from utils.safe_http import safe_http_json
    payload_obj = {
        "title": params.get("title"),
        "prompt": params.get("prompt"),
        "tags": params.get("style_tags"),
        "make_instrumental": bool(params.get("instrumental", True)),
        "model": params.get("model_version", "v4"),
    }
    data = await asyncio.to_thread(
        safe_http_json,
        endpoint,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        payload=payload_obj,
        timeout=30.0,
    )
    data_dict = data if isinstance(data, dict) else {"raw": data}
    return {
        "status": "success",
        "track_url": data_dict.get("audio_url") or data_dict.get("url") or "",
        "title": str(params.get("title") or ""),
        "content": json.dumps(data_dict, ensure_ascii=False),
    }


async def _run_calendar_publish_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    from backend.operations_calendar import operations_calendar
    offset_h = max(1, int(params.get("auto_offset_hours") or 24))
    start_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_h)
    end_dt = start_dt + datetime.timedelta(minutes=30)
    title = str(params.get("title") or node.get("title") or "Publishing-Termin").strip()
    channel = str(params.get("channel") or "linkedin").strip()
    asset_path = str(params.get("asset_path") or "").strip()
    notes = str(params.get("notes") or "").strip()
    if asset_path:
        notes = f"{notes}\nAsset: {asset_path}".strip()
    wf_ref = str(node.get("workflow_id") or "").strip()
    n8n_act = str(params.get("n8n_webhook_action") or "").strip()
    if wf_ref or n8n_act:
        notes = f"{notes}\n[Workflow: {wf_ref}, Channel: {channel}, Action: {n8n_act}]".strip()
    ev = await asyncio.to_thread(
        operations_calendar.create_event,
        {
            "title": f"[{channel.upper()}] {title}",
            "start": start_dt.isoformat(timespec="minutes"),
            "end": end_dt.isoformat(timespec="minutes"),
            "category": "publishing",
            "notes": notes,
        },
    )
    ev_id = ev.get("id") if isinstance(ev, dict) else ""
    return {
        "status": "success",
        "calendar_event_id": ev_id,
        "scheduled_at": start_dt.isoformat(),
        "channel": channel,
        "content": f"Publishing-Termin '{title}' ({channel}) im Kalender angelegt: `{start_dt.isoformat()}` (ID: `{ev_id}`).",
    }


async def _run_image_gen_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        for val in (upstream or {}).values():
            if isinstance(val, dict) and val.get("content"):
                prompt = str(val["content"])[:400]
                break
    if not prompt:
        prompt = str(node.get("title") or "Editorial cover graphic")
    from fastapi import HTTPException

    from backend.image_generate import ImageGenerateToolRequest, api_tool_image_generate
    try:
        req_obj = ImageGenerateToolRequest(
            prompt=f"{prompt} ({params.get('style_preset', 'editorial_clean')}, aspect {params.get('aspect_ratio', '16:9')})",
            model=str(params.get("model") or "google/gemini-2.5-flash-image"),
            provider=str(params.get("provider") or "openrouter"),
            session_id=str(node.get("kanban_task_id") or node.get("id") or "dag_image_gen"),
        )
        res = await api_tool_image_generate(req_obj)
    except HTTPException as hex_err:
        return {
            "status": "error",
            "image_path": "",
            "prompt": prompt,
            "content": "",
            "error": str(hex_err.detail),
        }
    res_dict = res if isinstance(res, dict) else {"raw": res}
    return {
        "status": "success" if res_dict.get("status") != "error" else "error",
        "image_path": res_dict.get("path") or res_dict.get("url") or res_dict.get("image_url") or "",
        "prompt": prompt,
        "content": json.dumps(res_dict, ensure_ascii=False),
        "error": str(res_dict.get("error") or ""),
    }


_CORE_HANDLERS: Dict[str, PluginHandler] = {
    "ffmpeg": _run_ffmpeg_plugin,
    "kinocut": _run_kinocut_plugin,
    "tts": _run_tts_plugin,
    "suno": _run_suno_plugin,
    "image_gen": _run_image_gen_plugin,
    "calendar_publish": _run_calendar_publish_plugin,
}


async def execute_workflow_node_plugin(
    plugin_id: str,
    node: Dict[str, Any],
    upstream: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Zentraler Ausfuehrungs-Chokepoint fuer alle Core- und 3rd-Party-Node-Plugins."""
    spec = get_workflow_node_plugin(plugin_id)
    if not spec:
        return {"status": "error", "error": f"Unbekanntes Node-Plugin: '{plugin_id}'", "content": ""}

    from backend.tool_runtime import enforce_tool_execution, guard_result
    gate = enforce_tool_execution(
        # M75: rechenschaftsfähiger Engine-Akteur statt leerer agent_id (Fail-closed)
        agent_id="workflow_engine",
        session_id=str(node.get("kanban_task_id") or node.get("id") or "dag_plugin"),
        tool_name=f"node_plugin:{spec['plugin_id']}",
        args=dict(node.get("plugin_params") or {}),
    )
    if not gate.get("allowed"):
        return {"status": "error", "error": gate.get("reason", "Node-Plugin durch ToolRuntime blockiert"), "content": ""}

    # Defaults aus Schema + User-Werte + Upstream-Templates aufloesen
    merged: Dict[str, Any] = {}
    for pdef in spec.get("params_schema") or []:
        if isinstance(pdef, dict) and pdef.get("key"):
            merged[pdef["key"]] = pdef.get("default")
    if isinstance(node.get("plugin_params"), dict):
        merged.update(node["plugin_params"])
    resolved_params = resolve_upstream_templates(merged, upstream or {})

    handler = _CORE_HANDLERS.get(spec["plugin_id"])
    if handler:
        # F10: auch Core-Node-Handler liefern externe/untrusted Daten.
        res = await handler(resolved_params, node, upstream or {})
        return guard_result(f"node_plugin:{spec['plugin_id']}", res)

    # Generischer 3rd-Party HTTP/MCP-Adapter fuer JSON-Plugins in plugins/workflow_nodes/
    adapter = str(spec.get("adapter") or "http").lower()
    if adapter == "mcp" and spec.get("mcp_tool"):
        from backend.tool_runtime import execute_agent_tool
        return await execute_agent_tool(
            tool_name=str(spec["mcp_tool"]),
            args=resolved_params,
            agent_id=str(node.get("agent_id") or "default"),
            session_id=str(node.get("kanban_task_id") or node.get("id") or "dag_plugin"),
            flightlog_run_id=str(node.get("_dag_run_id") or node.get("kanban_task_id") or ""),
        )
    if adapter == "http" and spec.get("http_endpoint"):
        from utils.egress_guard import EgressBlocked, check_target_url
        from utils.safe_http import safe_http_request, webhook_signature_headers

        # D06/HIGH: das Plugin deklariert `webhook_url` als Steuerungsfeld —
        # es muss aus resolved_params kommen (sonst greift die UI-Control ins
        # Leere). Fallback nur auf den deklarierten http_endpoint.
        url_from_params = bool(resolved_params.get("webhook_url"))
        raw_endpoint = resolved_params.get("webhook_url") or spec.get("http_endpoint")
        endpoint_url = str(raw_endpoint or "").strip()
        if not endpoint_url:
            return {"status": "blocked", "error": "missing_webhook_url", "content": ""}

        action = str(resolved_params.get("action") or spec.get("action") or "").strip()
        is_execution_webhook = (
            str(spec.get("plugin_id") or "") == "n8n_webhook"
            or "/webhook/" in endpoint_url
            or bool(action)
        )

        # D06/HIGH: das aus resolved_params (und damit aus UI/Upstream)
        # stammende Webhook-Ziel vor dem Request gegen die Egress-Regeln
        # pruefen — kein Key/HMAC an ein manipuliertes Ziel (SSRF/Exfil-Schutz).
        # Reine 3rd-Party-APIs mit festem, lokal deklariertem http_endpoint
        # bleiben unberuehrt (keine Env-Allowlist noetig).
        if url_from_params or is_execution_webhook:
            try:
                check_target_url(endpoint_url)
            except (EgressBlocked, ValueError) as exc:
                logger.warning("Node-Plugin %s: Ziel blockiert (%s)", spec["plugin_id"], exc)
                return {
                    "status": "blocked",
                    "error": f"target_url_blocked: {exc}",
                    "content": "",
                }

        method = str(spec.get("http_method") or "POST").strip().upper()
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if isinstance(spec.get("headers"), dict):
            headers.update({str(k): str(v) for k, v in spec["headers"].items()})

        auth_cfg = spec.get("auth") if isinstance(spec.get("auth"), dict) else {}
        env_var = str(auth_cfg.get("env_var") or spec.get("auth_env_var") or "").strip()  # type: ignore[union-attr]
        if env_var:
            secret_val = str(os.environ.get(env_var) or "").strip()
            if not secret_val:
                return {
                    "status": "planned",
                    "planned_only": True,
                    "reason": "api_key_missing",
                    "missing_env": env_var,
                    "content": (
                        f"[{spec.get('label') or spec['plugin_id']} VST-Adapter] "
                        f"API-Key `{env_var}` fehlt fuer Live-Ausfuehrung."
                    ),
                }
            auth_type = str(auth_cfg.get("type") or "bearer").strip().lower()  # type: ignore[union-attr]
            if auth_type == "bearer":
                prefix = str(auth_cfg.get("prefix") if auth_cfg.get("prefix") is not None else "Bearer ")  # type: ignore[union-attr]
                headers[str(auth_cfg.get("header_name") or "Authorization")] = f"{prefix}{secret_val}"  # type: ignore[union-attr]
            elif auth_type == "header":
                headers[str(auth_cfg.get("header_name") or "X-API-Key")] = secret_val  # type: ignore[union-attr]
            elif auth_type == "query":
                sep = "&" if "?" in endpoint_url else "?"
                q_param = str(auth_cfg.get("query_param") or "api_key")  # type: ignore[union-attr]
                endpoint_url = f"{endpoint_url}{sep}{urllib.parse.quote(q_param)}={urllib.parse.quote(secret_val)}"

        # Optionales Request-Mapping fuer 3rd-Party-APIs
        req_mapping = spec.get("request_mapping") if isinstance(spec.get("request_mapping"), dict) else None
        if req_mapping:
            body_obj = {
                str(out_k): resolved_params.get(str(in_k), resolved_params.get(str(out_k)))
                for out_k, in_k in req_mapping.items()
            }
        else:
            body_obj = {"params": resolved_params, "node_id": node.get("id")}

        # D06/HIGH: die im Plugin deklarierten Steuerungsfelder kommen aus
        # resolved_params und gehoeren an das Empfaenger-Schema (action,
        # content/payload_text, executed_at) — nicht nur in `params`.
        if action:
            body_obj["action"] = action
        payload_text = resolved_params.get("payload_text")
        if payload_text is None:
            payload_text = resolved_params.get("content")
        if payload_text is not None:
            body_obj["content"] = str(payload_text)
        body_obj.setdefault("executed_at", datetime.datetime.now(datetime.timezone.utc).isoformat())

        # D06/HIGH: exakt derselbe kompakte Body wie beim n8n-Empfaenger
        # signieren (JSON.stringify(body) == Python separators=(',', ':')).
        # Ohne konfiguriertes HMAC-Secret weist der Empfaenger den Request ab.
        body_bytes = json.dumps(
            body_obj, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")
        headers.update(webhook_signature_headers(body_bytes))

        # safe_http_request liefert (status, headers, bytes) — kein Dict und
        # kein json_body-Argument. Der alte Aufruf warf TypeError/AttributeError,
        # wodurch alle installierten JSON-Plugins nicht ausführbar waren.
        _status_code, resp_headers, raw_bytes = await asyncio.to_thread(
            safe_http_request,
            endpoint_url,
            method=method,
            headers=headers,
            data=body_bytes if method != "GET" else None,
            timeout=float(spec.get("timeout_sec") or 30.0),
        )
        ctype = str(resp_headers.get("content-type") or "").lower()

        # Binaer-Download direkt in Showroom-Medienverzeichnis speichern
        is_binary = (
            str(spec.get("response_type") or "").lower() == "binary"
            or any(ctype.startswith(p) for p in ("audio/", "video/", "image/", "application/octet-stream"))
        )
        if is_binary:
            ext = "bin"
            if "mpeg" in ctype or "mp3" in ctype:
                ext = "mp3"
            elif "wav" in ctype:
                ext = "wav"
            elif "mp4" in ctype:
                ext = "mp4"
            elif "png" in ctype:
                ext = "png"
            elif "jpeg" in ctype or "jpg" in ctype:
                ext = "jpg"
            media_dir = _showroom_media_dir(node, "02_Medien")
            out_file = os.path.join(media_dir, f"{spec['plugin_id']}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}")
            with open(out_file, "wb") as bf:
                bf.write(raw_bytes)
            out_payload: Dict[str, Any] = {
                "status": "success",
                "media_path": out_file,
                "content_type": ctype,
                "content": f"[{spec.get('label') or spec['plugin_id']}] Media-Datei gespeichert: `{out_file}`",
            }
            if ext in ("mp3", "wav"):
                out_payload["audio_path"] = out_file
            elif ext == "mp4":
                out_payload["video_path"] = out_file
            elif ext in ("png", "jpg"):
                out_payload["image_path"] = out_file
            return out_payload

        data = json.loads(raw_bytes.decode("utf-8", errors="replace")) if raw_bytes else {}
        data_dict = data if isinstance(data, dict) else {"raw": data}

        # Asynchrones Job-Polling falls poll_endpoint konfiguriert ist
        poll_tpl = str(spec.get("poll_endpoint") or "").strip()
        job_id = str(data_dict.get("job_id") or data_dict.get("task_id") or data_dict.get("id") or "").strip()
        if poll_tpl and job_id and str(data_dict.get("status") or "").lower() in ("queued", "pending", "processing", "running", ""):
            poll_url = poll_tpl.replace("{job_id}", urllib.parse.quote(job_id)).replace("{id}", urllib.parse.quote(job_id))
            max_polls = max(1, min(15, int(spec.get("max_polls") or 6)))
            poll_interval = max(0.2, min(10.0, float(spec.get("poll_interval_sec") or 2.0)))
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                _p_status, _p_headers, p_body = await asyncio.to_thread(
                    safe_http_request,
                    poll_url,
                    method="GET",
                    headers=headers,
                    timeout=20.0,
                )
                p_data = json.loads((p_body or b"{}").decode("utf-8", errors="replace"))
                if isinstance(p_data, dict):
                    data_dict = p_data
                    p_st = str(p_data.get("status") or "").lower()
                    if p_st in ("completed", "succeeded", "done", "ready", "success"):
                        break
                    if p_st in ("failed", "error", "cancelled"):
                        return {
                            "status": "error",
                            "error": str(p_data.get("error") or f"Async-Job {job_id} fehlgeschlagen"),
                            "content": json.dumps(data_dict, ensure_ascii=False),
                        }

        # D06/HIGH: Antwort validieren. Eine Ablehnung durch den Empfaenger
        # (HMAC-Fehler, 401/403, status=error/blocked) darf NIE als Erfolg
        # quittiert werden — sonst "Success ohne Wirkung" (S-1.5/S-1.7).
        resp_status = str(data_dict.get("status") or "").strip().lower()
        rejection_states = {
            "blocked", "error", "rejected", "denied", "invalid_signature",
            "unauthorized", "forbidden", "failed",
        }
        if int(_status_code) >= 400 or resp_status in rejection_states:
            logger.warning(
                "Node-Plugin %s: Webhook abgelehnt (HTTP %s, status=%s)",
                spec["plugin_id"], _status_code, resp_status or "<none>",
            )
            return {
                "status": "blocked",
                "error": resp_status or f"http_{_status_code}",
                "execution": "rejected",
                "content": json.dumps(data_dict, ensure_ascii=False),
                "data": data_dict,
            }

        # Ausfuehrende Webhooks muessen eine bestaetigte executionId liefern.
        # Unbestaetigte Antworten werden als `blocked` markiert (DLQ-Pfad),
        # statt still als `success` durchgereicht zu werden.
        if is_execution_webhook:
            accepted_states = {"success", "ok", "running", "queued", "accepted", "completed", "succeeded"}
            exec_id = str(
                data_dict.get("executionId") or data_dict.get("execution_id") or ""
            ).strip()
            if resp_status not in accepted_states or not exec_id:
                logger.warning(
                    "Node-Plugin %s: Execution unbestaetigt (status=%s, executionId=%r)",
                    spec["plugin_id"], resp_status or "<none>", exec_id,
                )
                return {
                    "status": "blocked",
                    "error": "execution_unconfirmed",
                    "execution": "unconfirmed",
                    "content": json.dumps(data_dict, ensure_ascii=False),
                    "data": data_dict,
                }

        # H4: externe Antwort darf die Steuerungsfelder des Ergebnisses nicht
        # ueberschreiben (status/content/error/media_path). Alle externen
        # Daten stehen zusaetzlich unter `data` zur Verfuegung.
        external = {
            k: v for k, v in data_dict.items()
            if k not in ("status", "content", "error", "media_path", "data")
        }
        result = {"status": "success", "content": json.dumps(data_dict, ensure_ascii=False), "data": external}
        result.update(external)
        return result

    return {"status": "error", "error": f"Kein Ausfuehrungs-Adapter fuer Plugin '{spec['plugin_id']}' konfiguriert.", "content": ""}


# =====================================================================
# BAUSTEIN-MARKTPLATZ (3RD-PARTY KATALOG & INSTALLATION)
# =====================================================================

WORKFLOW_NODE_MARKETPLACE_CATALOG: List[Dict[str, Any]] = [
    {
        "plugin_id": "udio",
        "label": "Udio AI Music",
        "category": "audio",
        "icon": "🎶",
        "adapter": "http",
        "source_name": "Udio",
        "source_url": "https://www.udio.com",
        "description": "Generiert komplette Songs, Intros und Hintergrundmusik per Prompt & Genre-Tags.",
        "http_endpoint": "https://api.udio.com/v1/generate",
        "outputs_schema": ["audio_path", "track_url", "content"],
        "params_schema": [
            {"key": "prompt", "label": "Musik-Prompt", "type": "textarea", "default": ""},
            {"key": "tags", "label": "Genre / Stimmung", "type": "text", "default": "cinematic, electronic, 118bpm"},
            {"key": "instrumental", "label": "Instrumental", "type": "checkbox", "default": True},
            {"key": "duration_sec", "label": "Dauer (s)", "type": "number", "default": 30, "min": 10, "max": 240, "step": 5},
        ],
    },
    {
        "plugin_id": "elevenlabs",
        "label": "ElevenLabs Voice & Dubbing",
        "category": "audio",
        "icon": "🗣️",
        "adapter": "http",
        "source_name": "ElevenLabs",
        "source_url": "https://elevenlabs.io",
        "description": "Hochwertige KI-Stimmen, Voice-Cloning und automatisches Video-Dubbing in 29+ Sprachen.",
        "http_endpoint": "https://api.elevenlabs.io/v1/text-to-speech",
        "outputs_schema": ["audio_path", "voice_id", "content"],
        "params_schema": [
            {"key": "text", "label": "Text ({{upstream.step_1.content}})", "type": "textarea", "default": ""},
            {"key": "voice_id", "label": "Voice-ID", "type": "text", "default": "21m00Tcm4TlvDq8ikWAM"},
            {"key": "model_id", "label": "Modell", "type": "select", "default": "eleven_multilingual_v2", "options": ["eleven_multilingual_v2", "eleven_turbo_v2_5"]},
            {"key": "stability", "label": "Stabilitaet (0.0-1.0)", "type": "number", "default": 0.5, "min": 0, "max": 1, "step": 0.05},
        ],
    },
    {
        "plugin_id": "whisper",
        "label": "Whisper / Deepgram STT",
        "category": "audio",
        "icon": "📝",
        "adapter": "http",
        "source_name": "OpenAI Whisper / Deepgram",
        "source_url": "https://deepgram.com",
        "description": "Transkribiert Audio/Video exakt mit Zeitstempeln (.srt/.vtt) fuer Untertitel und Repurposing.",
        "http_endpoint": "https://api.deepgram.com/v1/listen",
        "outputs_schema": ["srt_path", "transcript", "content"],
        "params_schema": [
            {"key": "input_path", "label": "Audio/Video-Pfad", "type": "text", "default": "{{upstream.step_1.video_path}}"},
            {"key": "language", "label": "Sprache", "type": "select", "default": "de", "options": ["de", "en", "fr", "es", "auto"]},
            {"key": "diarize", "label": "Sprechererkennung", "type": "checkbox", "default": True},
        ],
    },
    {
        "plugin_id": "runway",
        "label": "Runway Gen-3/Gen-4",
        "category": "video",
        "icon": "🎥",
        "adapter": "http",
        "source_name": "RunwayML",
        "source_url": "https://runwayml.com",
        "description": "Text-to-Video und Image-to-Video Generierung fuer B-Roll, Intro-Szenen und Visuals.",
        "http_endpoint": "https://api.dev.runwayml.com/v1/image_to_video",
        "outputs_schema": ["video_path", "task_id", "content"],
        "params_schema": [
            {"key": "prompt", "label": "Szenen-Prompt", "type": "textarea", "default": ""},
            {"key": "image_url", "label": "Startbild (optional)", "type": "text", "default": "{{upstream.step_1.image_path}}"},
            {"key": "duration", "label": "Dauer (s)", "type": "select", "default": "5", "options": ["5", "10"]},
            {"key": "ratio", "label": "Format", "type": "select", "default": "1280:720", "options": ["1280:720", "720:1280", "960:960"]},
        ],
    },
    {
        "plugin_id": "kling",
        "label": "Kling AI Video",
        "category": "video",
        "icon": "🎞️",
        "adapter": "http",
        "source_name": "Kling AI",
        "source_url": "https://klingai.com",
        "description": "Realistische KI-Videosequenzen mit Kamerasteuerung und Lip-Sync.",
        "http_endpoint": "https://api.klingai.com/v1/videos/text2video",
        "outputs_schema": ["video_path", "content"],
        "params_schema": [
            {"key": "prompt", "label": "Video-Prompt", "type": "textarea", "default": ""},
            {"key": "aspect_ratio", "label": "Format", "type": "select", "default": "9:16", "options": ["9:16", "16:9", "1:1"]},
            {"key": "duration", "label": "Dauer (s)", "type": "select", "default": "5", "options": ["5", "10"]},
        ],
    },
    {
        "plugin_id": "heygen",
        "label": "HeyGen AI Avatar",
        "category": "video",
        "icon": "🧑‍💼",
        "adapter": "http",
        "source_name": "HeyGen",
        "source_url": "https://www.heygen.com",
        "description": "Erstellt Sprecher-Videos mit deinem digitalen Avatar direkt aus einem Skript.",
        "http_endpoint": "https://api.heygen.com/v2/video/generate",
        "outputs_schema": ["video_path", "video_url", "content"],
        "params_schema": [
            {"key": "script", "label": "Sprecher-Skript", "type": "textarea", "default": "{{upstream.step_1.content}}"},
            {"key": "avatar_id", "label": "Avatar-ID", "type": "text", "default": "default_avatar"},
            {"key": "voice_id", "label": "Voice-ID", "type": "text", "default": ""},
            {"key": "aspect_ratio", "label": "Format", "type": "select", "default": "9:16", "options": ["9:16", "16:9", "1:1"]},
        ],
    },
    {
        "plugin_id": "descript",
        "label": "Descript Edit & Captions",
        "category": "video",
        "icon": "🪄",
        "adapter": "http",
        "source_name": "Descript",
        "source_url": "https://www.descript.com",
        "description": "Entfernt Fuellwoerter, verbessert Studio-Sound und exportiert untertitelte Clips.",
        "http_endpoint": "https://api.descript.com/v1/projects",
        "outputs_schema": ["video_path", "content"],
        "params_schema": [
            {"key": "input_path", "label": "Video-Pfad", "type": "text", "default": "{{upstream.step_1.video_path}}"},
            {"key": "studio_sound", "label": "Studio Sound aktivieren", "type": "checkbox", "default": True},
            {"key": "remove_filler_words", "label": "Fuellwoerter entfernen", "type": "checkbox", "default": True},
        ],
    },
    {
        "plugin_id": "flux_comfyui",
        "label": "Flux / ComfyUI",
        "category": "design",
        "icon": "🎨",
        "adapter": "http",
        "source_name": "ComfyUI / Black Forest Labs",
        "source_url": "https://www.comfy.org",
        "description": "Lokale oder Cloud-Bildgenerierung ueber eigene ComfyUI-Workflows (Zero-Egress-faehig).",
        "http_endpoint": "http://127.0.0.1:8188/prompt",
        "outputs_schema": ["image_path", "content"],
        "params_schema": [
            {"key": "prompt", "label": "Bild-Prompt", "type": "textarea", "default": ""},
            {"key": "width", "label": "Breite", "type": "number", "default": 1024, "min": 512, "max": 2048, "step": 64},
            {"key": "height", "label": "Hoehe", "type": "number", "default": 1024, "min": 512, "max": 2048, "step": 64},
            {"key": "steps", "label": "Sampling Steps", "type": "number", "default": 20, "min": 4, "max": 50, "step": 1},
        ],
    },
    {
        "plugin_id": "canva",
        "label": "Canva Design Export",
        "category": "design",
        "icon": "🖌️",
        "adapter": "http",
        "source_name": "Canva Connect",
        "source_url": "https://www.canva.com",
        "description": "Befuellt Canva-Brand-Templates automatisch mit Text/Bildern und exportiert PNG/PDF.",
        "http_endpoint": "https://api.canva.com/rest/v1/autofills",
        "outputs_schema": ["image_path", "pdf_path", "content"],
        "params_schema": [
            {"key": "brand_template_id", "label": "Brand-Template-ID", "type": "text", "default": ""},
            {"key": "headline", "label": "Headline", "type": "text", "default": "{{topic}}"},
            {"key": "export_format", "label": "Export-Format", "type": "select", "default": "png", "options": ["png", "pdf", "jpg"]},
        ],
    },
    {
        "plugin_id": "bannerbear",
        "label": "Bannerbear Auto-Visuals",
        "category": "design",
        "icon": "🐻",
        "adapter": "http",
        "source_name": "Bannerbear",
        "source_url": "https://www.bannerbear.com",
        "description": "Rendert Social-Media-Karten, Thumbnails und Karussell-Slides per Template-API.",
        "http_endpoint": "https://api.bannerbear.com/v2/images",
        "outputs_schema": ["image_path", "image_url", "content"],
        "params_schema": [
            {"key": "template_id", "label": "Template-UID", "type": "text", "default": ""},
            {"key": "title", "label": "Titel-Layer", "type": "text", "default": "{{topic}}"},
            {"key": "subtitle", "label": "Untertitel-Layer", "type": "text", "default": ""},
        ],
    },
    {
        "plugin_id": "marp_slides",
        "label": "Marp / Pandoc Slides & PDF",
        "category": "docs",
        "icon": "📑",
        "adapter": "mcp",
        "source_name": "Marp / Archon Slides",
        "source_url": "https://marp.app",
        "description": "Wandelt Markdown-Decks in Praesentationen, LinkedIn-Carousel-PDFs oder HTML-Slides um.",
        "mcp_tool": "archon__export_slides",
        "outputs_schema": ["pdf_path", "content"],
        "params_schema": [
            {"key": "markdown", "label": "Slide-Markdown ({{upstream.step_1.content}})", "type": "textarea", "default": ""},
            {"key": "theme", "label": "Theme", "type": "select", "default": "default", "options": ["default", "gaia", "uncover"]},
            {"key": "export_format", "label": "Format", "type": "select", "default": "pdf", "options": ["pdf", "pptx", "html"]},
        ],
    },
    {
        "plugin_id": "opendockit",
        "label": "OpenDocKit Office & PDF",
        "category": "docs",
        "icon": "📄",
        "adapter": "mcp",
        "source_name": "OpenDocKit MCP",
        "source_url": "https://pypi.org/project/opendockit/",
        "description": "Erzeugt, prueft und konvertiert strukturierte DOCX-, XLSX- und PDF-Dokumente.",
        "mcp_tool": "opendockit__render_document",
        "outputs_schema": ["doc_path", "content"],
        "params_schema": [
            {"key": "source_content", "label": "Inhalt ({{upstream.step_1.content}})", "type": "textarea", "default": ""},
            {"key": "output_format", "label": "Ziel-Format", "type": "select", "default": "pdf", "options": ["pdf", "docx", "xlsx"]},
            {"key": "template_name", "label": "Vorlage (optional)", "type": "text", "default": ""},
        ],
    },
    {
        "plugin_id": "gamma",
        "label": "Gamma AI Presentations",
        "category": "docs",
        "icon": "✨",
        "adapter": "http",
        "source_name": "Gamma",
        "source_url": "https://gamma.app",
        "description": "Generiert strukturierte Pitch-Decks, Handouts und Web-Dokumente per KI.",
        "http_endpoint": "https://public-api.gamma.app/v0.2/generations",
        "outputs_schema": ["deck_url", "content"],
        "params_schema": [
            {"key": "input_text", "label": "Briefing / Gliederung", "type": "textarea", "default": "{{upstream.step_1.content}}"},
            {"key": "num_cards", "label": "Anzahl Karten/Slides", "type": "number", "default": 8, "min": 3, "max": 30, "step": 1},
            {"key": "language", "label": "Sprache", "type": "select", "default": "de", "options": ["de", "en"]},
        ],
    },
    {
        "plugin_id": "firecrawl",
        "label": "Firecrawl Web-to-Markdown",
        "category": "research",
        "icon": "🔥",
        "adapter": "http",
        "source_name": "Firecrawl",
        "source_url": "https://www.firecrawl.dev",
        "description": "Crawlt Webseiten sauber in LLM-taugliches Markdown oder strukturierte JSON-Extrakte.",
        "http_endpoint": "https://api.firecrawl.dev/v1/scrape",
        "outputs_schema": ["markdown", "content"],
        "params_schema": [
            {"key": "url", "label": "Ziel-URL", "type": "text", "default": ""},
            {"key": "only_main_content", "label": "Nur Hauptinhalt extrahieren", "type": "checkbox", "default": True},
            {"key": "max_depth", "label": "Crawl-Tiefe", "type": "number", "default": 1, "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "plugin_id": "apify",
        "label": "Apify Actor Scraper",
        "category": "research",
        "icon": "🕷️",
        "adapter": "http",
        "source_name": "Apify",
        "source_url": "https://apify.com",
        "description": "Startet Apify-Scraper (LinkedIn, YouTube, TikTok, Maps, Google Search) fuer strukturierte Rohdaten.",
        "http_endpoint": "https://api.apify.com/v2/acts",
        "outputs_schema": ["items", "content"],
        "params_schema": [
            {"key": "actor_id", "label": "Actor-ID", "type": "text", "default": "apify/web-scraper"},
            {"key": "query_or_url", "label": "Suchbegriff / URL", "type": "text", "default": "{{topic}}"},
            {"key": "max_items", "label": "Max. Datensaetze", "type": "number", "default": 20, "min": 1, "max": 500, "step": 5},
        ],
    },
    {
        "plugin_id": "yt_transcript",
        "label": "YouTube Transcript Extractor",
        "category": "research",
        "icon": "📺",
        "adapter": "mcp",
        "source_name": "Archon / YouTube MCP",
        "source_url": "https://github.com/youtube",
        "description": "Extrahiert Zeitstempel-Transkripte und Kapitel aus YouTube-Videos als Content-Basis.",
        "mcp_tool": "archon__youtube_transcript",
        "outputs_schema": ["transcript", "content"],
        "params_schema": [
            {"key": "video_url", "label": "YouTube-URL", "type": "text", "default": ""},
            {"key": "language", "label": "Bevorzugte Sprache", "type": "select", "default": "de", "options": ["de", "en", "auto"]},
        ],
    },
    {
        "plugin_id": "patsnap",
        "label": "PatSnap Patent & Research",
        "category": "research",
        "icon": "🔬",
        "adapter": "mcp",
        "source_name": "PatSnap MCP",
        "source_url": "https://www.patsnap.com",
        "description": "Recherchiert Patente, Prior Art, Anmelder und Rechtsstand ueber den PatSnap-MCP-Server.",
        "mcp_tool": "patsnap__search_patents",
        "outputs_schema": ["patents", "content"],
        "params_schema": [
            {"key": "query", "label": "Suchbegriff / Technologie", "type": "text", "default": "{{topic}}"},
            {"key": "limit", "label": "Max. Treffer", "type": "number", "default": 10, "min": 1, "max": 50, "step": 1},
        ],
    },
    {
        "plugin_id": "n8n_webhook",
        "label": "n8n Automation Webhook",
        "category": "business",
        "icon": "⚡",
        "adapter": "http",
        "source_name": "n8n",
        "source_url": "https://n8n.io",
        "description": "Uebergibt freigegebene Workflow-Ergebnisse an beliebige n8n-Automationen.",
        "http_endpoint": "http://127.0.0.1:5678/webhook/archon-execution",
        "outputs_schema": ["webhook_response", "content"],
        "params_schema": [
            {"key": "webhook_url", "label": "n8n Webhook-URL", "type": "text", "default": "http://127.0.0.1:5678/webhook/archon-execution"},
            {"key": "action", "label": "Action-Name", "type": "text", "default": "publish_content"},
            {"key": "payload_text", "label": "Nutzdaten ({{upstream.step_1.content}})", "type": "textarea", "default": ""},
        ],
    },
    {
        "plugin_id": "youtube_publish",
        "label": "YouTube Data Upload",
        "category": "business",
        "icon": "▶️",
        "adapter": "http",
        "source_name": "YouTube Data API v3",
        "source_url": "https://developers.google.com/youtube/v3",
        "description": "Laedt fertige Videos/Shorts mit Titel, Beschreibung, Tags und Sichtbarkeit zu YouTube hoch.",
        "http_endpoint": "https://www.googleapis.com/upload/youtube/v3/videos",
        "outputs_schema": ["video_id", "youtube_url", "content"],
        "params_schema": [
            {"key": "video_path", "label": "Video-Datei", "type": "text", "default": "{{upstream.step_1.video_path}}"},
            {"key": "title", "label": "Video-Titel", "type": "text", "default": "{{topic}}"},
            {"key": "privacy_status", "label": "Sichtbarkeit", "type": "select", "default": "unlisted", "options": ["private", "unlisted", "public"]},
            {"key": "tags", "label": "Tags (Komma)", "type": "text", "default": "AI, Automation, Archon"},
        ],
    },
    {
        "plugin_id": "linkedin_publish",
        "label": "LinkedIn Post & Carousel",
        "category": "business",
        "icon": "💼",
        "adapter": "http",
        "source_name": "LinkedIn / Typefully / n8n",
        "source_url": "https://developer.linkedin.com",
        "description": "Veroeffentlicht Text-Posts, Dokument-Karussells (PDF) oder Videos nach HITL-Freigabe.",
        "http_endpoint": "http://127.0.0.1:5678/webhook/archon-execution",
        "outputs_schema": ["post_url", "content"],
        "params_schema": [
            {"key": "post_text", "label": "Post-Text", "type": "textarea", "default": "{{upstream.step_1.content}}"},
            {"key": "attachment_path", "label": "PDF/Bild/Video (optional)", "type": "text", "default": ""},
            {"key": "visibility", "label": "Sichtbarkeit", "type": "select", "default": "PUBLIC", "options": ["PUBLIC", "CONNECTIONS"]},
        ],
    },
]


def list_marketplace_plugins() -> List[Dict[str, Any]]:
    """Liefert den kompletten Baustein-Marktplatz inkl. Installationsstatus."""
    installed_map = {p["plugin_id"]: p for p in list_workflow_node_plugins()}
    items: List[Dict[str, Any]] = []
    # Core-Plugins als vorinstalliert mit auffuehren
    for pid, spec in CORE_NODE_PLUGINS.items():
        items.append({
            **spec,
            "source_name": "Archon Core",
            "source_url": "internal://archon-os",
            "installed": True,
            "core": True,
        })
    # 3rd-Party-Katalog
    catalog_ids = set()
    for spec in WORKFLOW_NODE_MARKETPLACE_CATALOG:
        pid = spec["plugin_id"]
        catalog_ids.add(pid)
        items.append({
            **spec,
            "installed": pid in installed_map,
            "core": False,
        })
    # Benutzerdefinierte Custom-Plugins aus plugins/workflow_nodes/
    for pid, spec in installed_map.items():
        if pid not in CORE_NODE_PLUGINS and pid not in catalog_ids:
            items.append({
                **spec,
                "installed": True,
                "core": False,
                "custom": True,
            })
    return items


def install_marketplace_plugin(plugin_id: str) -> Dict[str, Any]:
    """Installiert ein Plugin aus dem Marktplatz als deklaratives Manifest in plugins/workflow_nodes/."""
    pid = re.sub(r"[^a-zA-Z0-9_-]+", "", str(plugin_id or "").strip().lower())
    if not pid:
        raise ValueError("plugin_id_required")
    if pid in CORE_NODE_PLUGINS:
        return {"status": "already_installed", "plugin": CORE_NODE_PLUGINS[pid]}
    spec = next((x for x in WORKFLOW_NODE_MARKETPLACE_CATALOG if x["plugin_id"] == pid), None)
    if not spec:
        raise KeyError(f"Plugin '{pid}' nicht im Marktplatz gefunden.")
    os.makedirs(PLUGINS_NODES_DIR, exist_ok=True)
    target = os.path.join(PLUGINS_NODES_DIR, f"{pid}.json")
    tmp = f"{target}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    return {"status": "installed", "plugin": {**spec, "installed": True, "third_party": True}}


def uninstall_marketplace_plugin(plugin_id: str) -> Dict[str, Any]:
    """Deinstalliert ein 3rd-Party-Plugin aus plugins/workflow_nodes/ (Core-Module geschuetzt)."""
    pid = re.sub(r"[^a-zA-Z0-9_-]+", "", str(plugin_id or "").strip().lower())
    if pid in CORE_NODE_PLUGINS:
        raise ValueError("Core-Bausteine koennen nicht deinstalliert werden.")
    target = os.path.join(PLUGINS_NODES_DIR, f"{pid}.json")
    if os.path.isfile(target):
        os.remove(target)
        return {"status": "uninstalled", "plugin_id": pid}
    return {"status": "not_installed", "plugin_id": pid}


def register_custom_marketplace_plugin(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Registriert und installiert ein benutzerdefiniertes 3rd-Party- / GitHub-Plugin."""
    source_url = str(payload.get("source_url") or payload.get("github_url") or "").strip()
    label = str(payload.get("label") or "").strip()
    if not label and source_url:
        label = source_url.rstrip("/").split("/")[-1].replace(".git", "")
    if not label:
        raise ValueError("label_or_source_required")

    raw_cat = str(payload.get("category") or "business").strip().lower()
    valid_cats = {"audio", "video", "design", "docs", "research", "business"}
    cat = raw_cat if raw_cat in valid_cats else "business"

    pid = re.sub(r"[^a-z0-9_-]+", "_", label.lower()).strip("_")[:48] or f"custom_{int(time.time())}"
    if pid in CORE_NODE_PLUGINS:
        pid = f"custom_{pid}"

    desc = str(payload.get("description") or "").strip() or (
        f"Benutzerdefiniertes Modul aus {source_url}" if source_url else "Benutzerdefiniertes Workflow-Plugin"
    )
    adapter = str(payload.get("adapter") or "http").strip().lower()
    if adapter not in ("http", "mcp", "local"):
        adapter = "http"

    spec: Dict[str, Any] = {
        "plugin_id": pid,
        "label": label,
        "category": cat,
        "icon": str(payload.get("icon") or "🔌").strip() or "🔌",
        "adapter": adapter,
        "source_name": source_url.split("/")[2] if source_url.startswith("http") and len(source_url.split("/")) > 2 else "Custom / GitHub",
        "source_url": source_url,
        "description": desc,
        "http_endpoint": str(payload.get("http_endpoint") or "").strip(),
        "mcp_tool": str(payload.get("mcp_tool") or "").strip(),
        "outputs_schema": ["content", "output_path"],
        "params_schema": [
            {"key": "input", "label": "Eingabe / Prompt ({{upstream.step_1.content}})", "type": "textarea", "default": ""},
            {"key": "source_ref", "label": "Quelle / Repo / Endpoint", "type": "text", "default": source_url},
            {"key": "extra_args", "label": "Zusatz-Parameter (JSON / Flags)", "type": "text", "default": ""},
        ],
        "custom": True,
    }
    os.makedirs(PLUGINS_NODES_DIR, exist_ok=True)
    target = os.path.join(PLUGINS_NODES_DIR, f"{pid}.json")
    tmp = f"{target}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    return {"status": "installed", "plugin": {**spec, "installed": True, "third_party": True}}
