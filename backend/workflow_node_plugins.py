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
import urllib.request
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
                lambda m: _lookup(m.group(1)) if _lookup(m.group(1)) is not None else m.group(0),
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
        "category": "media",
        "icon": "🎬",
        "adapter": "local",
        "description": "Schneidet, konvertiert, skaliert (9:16 / 16:9), brennt Untertitel/Watermarks ein und extrahiert Audio.",
        "outputs_schema": ["video_path", "audio_path", "thumbnail_path", "command", "content"],
        "params_schema": [
            {"key": "mode", "label": "Modus", "type": "select", "default": "clip_cut", "options": ["clip_cut", "aspect_9_16", "burn_subtitles", "extract_audio", "thumbnail_frame", "speed_ramp"]},
            {"key": "input_path", "label": "Eingabe-Datei ({{upstream.step_1.video_path}})", "type": "text", "default": "", "placeholder": "/opt/data/obsidian/.../input.mp4"},
            {"key": "start_sec", "label": "Start (Sekunden)", "type": "number", "default": 0, "min": 0, "max": 86400, "step": 0.5},
            {"key": "duration_sec", "label": "Dauer (Sekunden, 0 = voll)", "type": "number", "default": 30, "min": 0, "max": 3600, "step": 0.5},
            {"key": "aspect_ratio", "label": "Seitenverhaeltnis", "type": "select", "default": "9:16", "options": ["9:16", "16:9", "1:1", "4:5", "original"]},
            {"key": "resolution", "label": "Ziel-Aufloesung", "type": "select", "default": "1080x1920", "options": ["1080x1920", "1920x1080", "1080x1080", "1080x1350", "original"]},
            {"key": "fps", "label": "FPS", "type": "select", "default": "30", "options": ["24", "25", "30", "60", "original"]},
            {"key": "crf", "label": "Qualitaet (CRF 16-30)", "type": "number", "default": 21, "min": 14, "max": 35, "step": 1},
            {"key": "video_codec", "label": "Video-Codec", "type": "select", "default": "libx264", "options": ["libx264", "libx265", "copy"]},
            {"key": "audio_codec", "label": "Audio-Codec", "type": "select", "default": "aac", "options": ["aac", "mp3", "copy", "none"]},
            {"key": "audio_bitrate", "label": "Audio-Bitrate", "type": "select", "default": "192k", "options": ["128k", "192k", "256k", "320k"]},
            {"key": "subtitle_path", "label": "Untertitel (.srt/.ass, optional)", "type": "text", "default": "", "placeholder": "{{upstream.step_1.srt_path}}"},
            {"key": "watermark_text", "label": "Watermark-Text (optional)", "type": "text", "default": "", "placeholder": "@archon_os"},
            {"key": "output_format", "label": "Ausgabe-Format", "type": "select", "default": "mp4", "options": ["mp4", "mov", "webm", "mp3", "jpg"]},
            {"key": "dry_run", "label": "Nur Befehl planen (Dry-Run)", "type": "checkbox", "default": False},
        ],
    },
    "kinocut": {
        "plugin_id": "kinocut",
        "label": "KinoCut AI Repurpose",
        "category": "media",
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
        "category": "media",
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
        "category": "publishing",
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
# AUSFUEHRUNGS-ADAPTER
# =====================================================================

async def _run_ffmpeg_plugin(params: Dict[str, Any], node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(params.get("mode") or "clip_cut")
    out_fmt = str(params.get("output_format") or ("mp3" if mode == "extract_audio" else ("jpg" if mode == "thumbnail_frame" else "mp4"))).strip(".")
    media_dir = _showroom_media_dir(node, "02_Medien")
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(media_dir, f"ffmpeg_{mode}_{ts}.{out_fmt}")

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
        cmd += ["-vn", "-acodec", str(params.get("audio_codec") or "libmp3lame"), "-b:a", str(params.get("audio_bitrate") or "192k"), out_file]
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
            safe_sub = _safe_media_input_path(sub_path).replace("\\", "/").replace(":", "\\:")
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
            "status": "success",
            "planned_only": True,
            "reason": reason,
            "command": cmd_str,
            "video_path": out_file if out_fmt != "mp3" else "",
            "audio_path": out_file if out_fmt == "mp3" else "",
            "content": f"[FFmpeg ({reason})] Geplanter Befehl:\n`{cmd_str}`\nZiel: `{out_file}`",
        }

    proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
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
        "video_path": out_file if out_fmt not in ("mp3", "jpg") else "",
        "audio_path": out_file if out_fmt == "mp3" else "",
        "thumbnail_path": out_file if out_fmt == "jpg" else "",
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
    return {
        "status": "success",
        "clips": matrix.get("clips") or [],
        "clip_count": len(matrix.get("clips") or []),
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
            "status": "success",
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
            "status": "success",
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

    from utils.egress_guard import check_target_url
    safe_url = check_target_url(endpoint)
    payload = json.dumps({
        "title": params.get("title"),
        "prompt": params.get("prompt"),
        "tags": params.get("style_tags"),
        "make_instrumental": bool(params.get("instrumental", True)),
        "model": params.get("model_version", "v4"),
    }).encode("utf-8")
    req = urllib.request.Request(
        safe_url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )

    def _call() -> Dict[str, Any]:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    data = await asyncio.to_thread(_call)
    return {
        "status": "success",
        "track_url": data.get("audio_url") or data.get("url") or "",
        "title": str(params.get("title") or ""),
        "content": json.dumps(data, ensure_ascii=False),
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
    ev = await asyncio.to_thread(
        operations_calendar.create_event,
        {
            "title": f"[{channel.upper()}] {title}",
            "start_at": start_dt.isoformat(),
            "end_at": end_dt.isoformat(),
            "category": "publishing",
            "description": notes,
            "metadata": {
                "channel": channel,
                "asset_path": asset_path,
                "n8n_webhook_action": params.get("n8n_webhook_action", ""),
                "workflow_id": node.get("workflow_id", ""),
            },
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
    from archon.routers.chat import image_generate
    res = await image_generate({
        "prompt": f"{prompt} ({params.get('style_preset', 'editorial_clean')}, aspect {params.get('aspect_ratio', '16:9')})",
        "model": str(params.get("model") or ""),
    })
    return {
        "status": "success" if res.get("status") != "error" else "error",
        "image_path": res.get("path") or res.get("url") or "",
        "prompt": prompt,
        "content": json.dumps(res, ensure_ascii=False),
        "error": res.get("error") or "",
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

    from backend.tool_runtime import enforce_tool_execution
    gate = enforce_tool_execution(
        agent_id="",
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
        return await handler(resolved_params, node, upstream or {})

    # Generischer 3rd-Party HTTP/MCP-Adapter fuer JSON-Plugins in plugins/workflow_nodes/
    adapter = str(spec.get("adapter") or "http").lower()
    if adapter == "mcp" and spec.get("mcp_tool"):
        from backend.tool_runtime import execute_agent_tool
        return await execute_agent_tool(
            tool_name=str(spec["mcp_tool"]),
            args=resolved_params,
            agent_id=str(node.get("agent_id") or "default"),
            session_id=str(node.get("kanban_task_id") or node.get("id") or "dag_plugin"),
        )
    if adapter == "http" and spec.get("http_endpoint"):
        from utils.egress_guard import check_target_url
        safe_url = check_target_url(str(spec["http_endpoint"]))
        req = urllib.request.Request(
            safe_url,
            data=json.dumps({"params": resolved_params, "node_id": node.get("id")}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        data = await asyncio.to_thread(lambda: json.loads(urllib.request.urlopen(req, timeout=30.0).read().decode("utf-8")))
        return {"status": "success", "content": json.dumps(data, ensure_ascii=False), **({k: v for k, v in data.items() if isinstance(data, dict)})}

    return {"status": "error", "error": f"Kein Ausfuehrungs-Adapter fuer Plugin '{spec['plugin_id']}' konfiguriert.", "content": ""}
