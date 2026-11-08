"""backend/settings_json.py — atomare, gelockte settings.json-Updates (F-07).

F-07: Fuenf Module (memory_consolidator, autonomy_settings, inbox_watcher,
internet_watchdog, concurrency_throttle) machten Read-Modify-Write auf
settings.json ohne Lock und ohne os.replace. Hintergrund-Thread (Watchdog)
und Settings-API schrieben gleichzeitig — der letzte Writer setzte fremde
Sektionen zurueck; ein Abbruch mitten im json.dump hinterliess eine kaputte
Datei, die alle Loader still auf Defaults fallen liess.

Dieses Blatt-Modul importiert nichts aus backend (keine Import-Zyklen).
"""

import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, Optional

_SETTINGS_LOCK = threading.RLock()


def _load_raw(path: str) -> Dict[str, Any]:
    """Tolerantes Laden: fehlende/kaputte Datei -> leeres Dict, nie Exception."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _write_atomic(path: str, data: Dict[str, Any]) -> None:
    """Temp-Datei im SELBEN Verzeichnis + fsync + os.replace (kein Halbstand)."""
    target = os.path.abspath(path)
    tdir = os.path.dirname(target) or "."
    os.makedirs(tdir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tdir, prefix=".settings_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_update_settings(
    path: str,
    mutator: Callable[[Dict[str, Any]], Any],
    loader: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Any:
    """Laden -> mutator(daten) -> atomar speichern — alles unter EINER Sperre.

    `mutator` aendert das geladene Dict in place und gibt optional ein
    Ergebnis zurueck. Wirft der Mutator, wird NICHT geschrieben.
    Rueckgabe: das Mutator-Ergebnis.
    """
    with _SETTINGS_LOCK:
        data = loader() if loader is not None else _load_raw(path)
        result = mutator(data)
        _write_atomic(path, data)
        return result


def load_settings(path: str) -> Dict[str, Any]:
    """Gelocktes, tolerantes Lesen (fuer konsistente Leser)."""
    with _SETTINGS_LOCK:
        return _load_raw(path)
