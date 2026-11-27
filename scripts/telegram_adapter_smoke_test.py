# -*- coding: utf-8 -*-
"""W6-D / D09-H1 — harter Adapter-Kompatibilitaets-Gate.

Vertrag fuer Partition E (``.github/workflows/ci.yml``)::

    python scripts/telegram_adapter_smoke_test.py

Exit 0 NUR, wenn der in ``docker-compose.yml`` read-only gemountete Adapter
gegen die im Manifest gepinnte HERMES-Image-API wirklich kompatibel ist:

1. Image-Digest im Manifest == Digest in ALLEN gepinnten Hermes-Services.
2. Mount (Quelle:Ziel:ro) exakt wie im Manifest im ``hermes``-Dienst aktiv.
3. Adapterdatei syntaktisch gueltig.
4. API-Signatur: register(ctx), die Registry-Hooks, TelegramAdapter(BasePlatformAdapter),
   register_platform(...)-Kwargs, die Image-Importmodule und die Archon-Patch-Marker.

Bei JEDEM Fehler Exit 1. Es werden keine Container gestartet, keine Secrets
eingebettet und keine fremden Dateien veraendert. Der Test ist bewusst
statisch: die API-Signatur ist im Manifest an den Image-Digest gebunden, ein
Image-Bump ohne Manifest-/Patch-Update macht das Gate rot.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "scripts" / "patches" / "MANIFEST.json"
COMPOSE_PATH = ROOT / "docker-compose.yml"
ADAPTER_PATH = ROOT / "scripts" / "patches" / "hermes_telegram_adapter.py"


class GateFehler(ValueError):
    """Ungueltige Manifest-/Compose-Struktur — kein Adapter-Fehler, aber Exit 1."""


def _lesen(pfad: Path) -> str:
    try:
        return pfad.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateFehler(f"Datei nicht lesbar: {pfad} ({exc})") from exc


def lade_manifest(pfad: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Manifest laden und die minimal noetige Struktur pruefen."""
    try:
        daten = json.loads(_lesen(pfad))
    except json.JSONDecodeError as exc:
        raise GateFehler(f"Ungueltiges Manifest_JSON: {exc}") from exc
    if not isinstance(daten, dict):
        raise GateFehler("Manifest muss ein JSON-Objekt sein")
    for schluessel in ("hermes_image", "adapter_mount", "adapter_api_contract"):
        if schluessel not in daten:
            raise GateFehler(f"Manifest-Sektion fehlt: {schluessel}")
    return daten


def _dienst_block(text: str, name: str) -> str:
    """Einen Compose-Dienstblock bis zum naechsten Dienst auf gleicher Ebene isolieren."""
    zeilen = text.splitlines()
    treffer = [i for i, zeile in enumerate(zeilen) if zeile == f"  {name}:"]
    if not treffer:
        raise GateFehler(f"Compose-Dienst fehlt: {name}")
    start = treffer[0]
    ende = len(zeilen)
    for i in range(start + 1, len(zeilen)):
        zeile = zeilen[i]
        if zeile.startswith("  ") and not zeile.startswith("   "):
            inhalt = zeile[2:]
            if inhalt and not inhalt.startswith(("#", "-")) and ":" in inhalt:
                ende = i
                break
    return "\n".join(zeilen[start:ende])


def pruefe_image_pin(manifest: dict[str, Any], compose_text: str) -> list[str]:
    """Der gepinnte Digest muss in allen gelisteten Hermes-Services stehen."""
    bild = manifest["hermes_image"]
    referenz = str(bild["reference"])
    digest = str(bild["digest"])
    if not digest.startswith("sha256:") or len(digest) != 71:
        return [f"Manifest-Digest ungueltig: {digest!r}"]
    pin = f"{referenz}@{digest}"
    fehler: list[str] = []
    services = bild.get("services", [])
    if not services:
        return ["Manifest: hermes_image.services ist leer"]
    for service in services:
        block = _dienst_block(compose_text, str(service))
        image_zeilen = [
            zeile.strip() for zeile in block.splitlines() if zeile.strip().startswith("image:")
        ]
        if not image_zeilen:
            fehler.append(f"{service}: keine image:-Zeile")
        elif not any(pin in zeile for zeile in image_zeilen):
            fehler.append(f"{service}: Image nicht auf {pin} gepinnt")
    return fehler


def pruefe_mount(manifest: dict[str, Any], compose_text: str) -> list[str]:
    """Der read-only Adapter-Mount muss exakt wie im Manifest aktiv sein."""
    mount = manifest["adapter_mount"]
    service = str(mount["service"])
    erwartet = (
        f"- {mount['source']}:{mount['target']}:{mount['mode']}"
    )
    block = _dienst_block(compose_text, service)
    zeilen = [zeile.strip() for zeile in block.splitlines()]
    fehler: list[str] = []
    treffer = [zeile for zeile in zeilen if "hermes_telegram_adapter.py" in zeile]
    if erwartet not in zeilen:
        fehler.append(f"{service}: Mount {erwartet!r} fehlt — Adapter-Patch nicht aktiv")
    elif len(treffer) != 1:
        fehler.append(f"{service}: {len(treffer)} Adapter-Mounts statt genau 1")
    return fehler


def pruefe_adapter_api(manifest: dict[str, Any], quelle: str) -> list[str]:
    """Echte API-Signatur-Pruefung des gemounteten Adapters gegen das Manifest."""
    try:
        compile(quelle, str(ADAPTER_PATH), "exec")
    except SyntaxError as exc:
        return [f"Adapter-Syntaxfehler: {exc}"]
    tree = ast.parse(quelle)
    vertrag = manifest["adapter_api_contract"]

    funktionen = {
        knoten.name: knoten
        for knoten in tree.body
        if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    klassen = {
        knoten.name: knoten for knoten in tree.body if isinstance(knoten, ast.ClassDef)
    }
    fehler: list[str] = []

    for vorgabe in vertrag["module_functions"]:
        name = str(vorgabe["name"])
        knoten = funktionen.get(name)
        if knoten is None:
            fehler.append(f"API-Funktion {name}() fehlt")
            continue
        erwartet = list(vorgabe["positional_args"])
        tatsaechlich = [arg.arg for arg in knoten.args.args]
        if tatsaechlich != erwartet:
            fehler.append(
                f"API-Signatur {name}(): {tatsaechlich!r} passt nicht zu {erwartet!r}"
            )

    for vorgabe in vertrag["classes"]:
        name = str(vorgabe["name"])
        klassen_knoten = klassen.get(name)
        if klassen_knoten is None:
            fehler.append(f"API-Klasse {name} fehlt")
            continue
        basen = {ast.unparse(basis) for basis in klassen_knoten.bases}
        for base in vorgabe["bases"]:
            if base not in basen:
                fehler.append(f"{name} erbt nicht von {base} (Basen: {sorted(basen)})")

    module = {
        knoten.module
        for knoten in ast.walk(tree)
        if isinstance(knoten, ast.ImportFrom) and knoten.module
    }
    for modul in vertrag["required_import_modules"]:
        if modul not in module:
            fehler.append(f"Image-Import {modul} fehlt im Adapter")

    register = funktionen.get("register")
    if register is None:
        fehler.append("Plugin-Entry-Point register(ctx) fehlt")
    else:
        kwargs: set[str] = set()
        for aufruf in ast.walk(register):
            if (
                isinstance(aufruf, ast.Call)
                and isinstance(aufruf.func, ast.Attribute)
                and aufruf.func.attr == "register_platform"
            ):
                kwargs |= {kw.arg for kw in aufruf.keywords if kw.arg is not None}
        for kw in vertrag["register_platform_kwargs"]:
            if kw not in kwargs:
                fehler.append(f"register_platform({kw}=...) fehlt")

    for marker, min_anzahl in vertrag["archon_patch_markers"].items():
        anzahl = quelle.count(str(marker))
        if anzahl < int(min_anzahl):
            fehler.append(
                f"Archon-Patch-Marker {marker!r}: {anzahl} Vorkommen < {min_anzahl}"
                " — Patch beim Image-Bump verloren"
            )
    return fehler


def alle_pruefungen(
    manifest_pfad: Path = MANIFEST_PATH,
    compose_pfad: Path = COMPOSE_PATH,
    adapter_pfad: Path = ADAPTER_PATH,
) -> tuple[list[str], list[str]]:
    """Alle Gates ausfuehren. Rueckgabe: (bestanden, fehler)."""
    bestanden: list[str] = []
    try:
        manifest = lade_manifest(manifest_pfad)
    except GateFehler as exc:
        return bestanden, [str(exc)]
    bestanden.append(f"Manifest geladen: {manifest_pfad.name}")

    compose = _lesen(compose_pfad)
    adapter = _lesen(adapter_pfad)
    bild = manifest["hermes_image"]
    pin = f"{bild['reference']}@{bild['digest']}"

    fehler = pruefe_image_pin(manifest, compose)
    if fehler:
        return bestanden, fehler
    bestanden.append(f"Image-Digest gepinnt in {len(bild['services'])} Services: {pin}")

    fehler = pruefe_mount(manifest, compose)
    if fehler:
        return bestanden, fehler
    bestanden.append("Read-only Adapter-Mount aktiv")

    fehler = pruefe_adapter_api(manifest, adapter)
    if fehler:
        return bestanden, fehler
    vertrag = manifest["adapter_api_contract"]
    bestanden.append(
        "Adapter-API kompatibel: "
        f"{len(vertrag['module_functions'])} Hooks, "
        f"{len(vertrag['register_platform_kwargs'])} register_platform-Kwargs, "
        f"{len(vertrag['archon_patch_markers'])} Patch-Marker"
    )
    return bestanden, []


def main(argv: list[str] | None = None) -> int:
    """CI-Vertrag: Exit 0 bei Kompatibilitaet, sonst Exit 1."""
    bestanden, fehler = alle_pruefungen()
    for zeile in bestanden:
        print(f"PASS  {zeile}")
    for zeile in fehler:
        print(f"FAIL  {zeile}")
    if fehler:
        print(
            f"ERGEBNIS: ROT ({len(fehler)} Fehler) — Adapter NICHT kompatibel mit dem "
            "gepinnten Hermes-Image"
        )
        return 1
    print("ERGEBNIS: GRUEN — Adapter-API kompatibel mit dem gepinnten Hermes-Image")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
