#!/usr/bin/env python3
"""
route_parity.py — Paritäts-Guard für Archon OS Routen

Vergleicht live openapi.json gegen Baseline.
- --save <datei>   : Holt http://127.0.0.1:8501/openapi.json, normalisiert, speichert
- --check <datei>  : Vergleicht live gegen Baseline, Exit-Code 0=gleich, 1=Abweichung, 2=Verbindungsfehler
- --file <datei>   : Nutzt lokale openapi.json statt HTTP (für Offline/CI)

Normalisierung: sortierte Liste "METHOD PATH" + Metadaten (paths count, operations count).
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


def fetch_openapi(url: str) -> dict:
    """Holt openapi.json via HTTP."""
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def load_openapi_file(path: str) -> dict:
    """Lädt openapi.json von Datei."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def normalize_openapi(data: dict) -> Tuple[List[str], Dict]:
    """
    Normalisiert OpenAPI-Spec zu vergleichbarer Form.
    Returns: (sorted_endpoints_list, metadata_dict)
    """
    paths = data.get('paths', {})
    endpoints = []
    for path, methods in paths.items():
        for method in methods:
            if method.lower() in ('get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'trace', 'websocket'):
                endpoints.append(f"{method.upper()} {path}")
    endpoints.sort()
    metadata = {
        'paths': len(paths),
        'operations': len(endpoints),
        'openapi_version': data.get('openapi', 'unknown'),
        'title': data.get('info', {}).get('title', ''),
        'version': data.get('info', {}).get('version', ''),
    }
    return endpoints, metadata


def save_baseline(endpoints: List[str], metadata: Dict, filepath: str) -> None:
    """Speichert Baseline als JSON."""
    baseline = {
        'endpoints': endpoints,
        'metadata': metadata,
        'generated_at': datetime.now(UTC).isoformat().replace('+00:00', 'Z'),
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)


def load_baseline(filepath: str) -> Tuple[List[str], Dict]:
    """Lädt Baseline aus JSON."""
    with open(filepath, 'r', encoding='utf-8') as f:
        baseline = json.load(f)
    return baseline['endpoints'], baseline['metadata']


def compare_endpoints(baseline_eps: List[str], live_eps: List[str]) -> Tuple[List[str], List[str]]:
    """Vergleicht zwei Endpunkt-Listen. Returns: (added, removed)."""
    base_set = set(baseline_eps)
    live_set = set(live_eps)
    added = sorted(live_set - base_set)
    removed = sorted(base_set - live_set)
    return added, removed


def print_diff(added: List[str], removed: List[str], baseline_meta: Dict, live_meta: Dict) -> None:
    """Gibt Unterschiede formatiert aus."""
    print(f"\n=== Routen-Parität Prüfung ===")
    print(f"Baseline: {baseline_meta['paths']} Pfade, {baseline_meta['operations']} Operationen")
    print(f"Live:     {live_meta['paths']} Pfade, {live_meta['operations']} Operationen")
    
    if not added and not removed:
        print("\n✅ IDENTISCH — Keine Abweichungen")
        return
    
    if added:
        print(f"\n🟢 HINZUGEFÜGT ({len(added)}):")
        for ep in added:
            print(f"  + {ep}")
    
    if removed:
        print(f"\n🔴 ENTFERNT ({len(removed)}):")
        for ep in removed:
            print(f"  - {ep}")


def main():
    parser = argparse.ArgumentParser(
        description='Archon OS Routen-Paritäts-Guard',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  # Baseline speichern (gegen laufenden Container)
  python route_parity.py --save baseline.json

  # Gegen Baseline prüfen
  python route_parity.py --check baseline.json

  # Gegen lokale Datei prüfen (Offline/CI)
  python route_parity.py --file openapi.json --check baseline.json
        """
    )
    parser.add_argument('--save', metavar='DATEI', help='Baseline speichern (holt via HTTP)')
    parser.add_argument('--check', metavar='DATEI', help='Live gegen Baseline prüfen')
    parser.add_argument('--file', metavar='OPENAPI.JSON', help='Lokale openapi.json statt HTTP')
    parser.add_argument('--url', default='http://127.0.0.1:8501/openapi.json', help='OpenAPI URL (Default: %(default)s)')
    
    args = parser.parse_args()
    
    if not args.save and not args.check:
        parser.error('Mindestens --save oder --check erforderlich')
    
    # Live-Daten holen
    if args.file:
        try:
            live_data = load_openapi_file(args.file)
            print(f"[INFO] Geladen von Datei: {args.file}")
        except Exception as e:
            print(f"[FEHLER] Konnte Datei nicht laden: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        try:
            live_data = fetch_openapi(args.url)
            print(f"[INFO] Geholt von: {args.url}")
        except urllib.error.URLError as e:
            print(f"[FEHLER] HTTP-Verbindungsfehler: {e}", file=sys.stderr)
            sys.exit(2)
        except json.JSONDecodeError as e:
            print(f"[FEHLER] Ungültiges JSON: {e}", file=sys.stderr)
            sys.exit(2)
        except Exception as e:
            print(f"[FEHLER] Unerwartet: {e}", file=sys.stderr)
            sys.exit(2)
    
    live_eps, live_meta = normalize_openapi(live_data)
    
    # Baseline speichern
    if args.save:
        save_baseline(live_eps, live_meta, args.save)
        print(f"[OK] Baseline gespeichert: {args.save} ({live_meta['operations']} Operationen, {live_meta['paths']} Pfade)")
        if not args.check:
            return
    
    # Gegen Baseline prüfen
    if args.check:
        try:
            baseline_eps, baseline_meta = load_baseline(args.check)
            print(f"[INFO] Baseline geladen: {args.check} ({baseline_meta['operations']} Operationen, {baseline_meta['paths']} Pfade)")
        except Exception as e:
            print(f"[FEHLER] Konnte Baseline nicht laden: {e}", file=sys.stderr)
            sys.exit(2)
        
        added, removed = compare_endpoints(baseline_eps, live_eps)
        print_diff(added, removed, baseline_meta, live_meta)
        
        if added or removed:
            sys.exit(1)  # Abweichung
        else:
            sys.exit(0)  # Identisch


if __name__ == '__main__':
    main()