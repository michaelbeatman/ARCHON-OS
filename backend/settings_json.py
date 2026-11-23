"""backend/settings_json.py — atomare, gelockte settings.json-Updates (F-07).

F-07: Fuenf Module (memory_consolidator, autonomy_settings, inbox_watcher,
internet_watchdog, concurrency_throttle) machten Read-Modify-Write auf
settings.json ohne Lock und ohne os.replace. Hintergrund-Thread (Watchdog)
und Settings-API schrieben gleichzeitig — der letzte Writer setzte fremde
Sektionen zurueck; ein Abbruch mitten im json.dump hinterliess eine kaputte
Datei, die alle Loader still auf Defaults fallen liess.

Dieses Blatt-Modul importiert nichts aus backend (keine Import-Zyklen).
"""
import logging
_archon_exc_logger = logging.getLogger("settings_json")

import errno
import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, Optional

_SETTINGS_LOCK = threading.RLock()


def _load_raw(path: str, *, strict: bool = False) -> Dict[str, Any]:
    """Laden mit Backup-Recovery.

    Frueher wurde eine kaputte Datei still als ``{}`` behandelt und der
    naechste atomare Update schrieb dieses leere Dict zurueck — damit waren
    alle uebrigen Sektionen (Themes, Rollen, Autonomie) dauerhaft weg. Jetzt
    wird bei Parse-Fehlern die letzte gueltige .bak herangezogen; gibt es
    keine, wird im Strict-Pfad (Schreiben) abgebrochen statt Daten zu
    vernichten.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        raise ValueError("settings.json hat kein Objekt als Wurzel")
    except Exception as _exc:
        _archon_exc_logger.warning("[settings_json] settings.json nicht lesbar: %s", _exc)
        bak = path + ".bak"
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _archon_exc_logger.warning("[settings_json] Backup wiederhergestellt: %s", bak)
                    return data
            except Exception as _bak_exc:
                _archon_exc_logger.error("[settings_json] Auch Backup unlesbar: %s", _bak_exc)
        if strict:
            raise RuntimeError(
                f"settings.json ist beschaedigt und kein gueltiges Backup vorhanden: {path}"
            ) from _exc
        return {}


def _write_atomic(path: str, data: Dict[str, Any]) -> None:
    """Temp-Datei + fsync + os.replace (kein Halbstand).

    C14: Im gehaerteten Container ist `/app` read-only und `settings.json` ein
    Bind-Mount. Dort kann weder die Temp-Datei im Zielverzeichnis liegen noch
    `os.replace()` den Mount-Point ersetzen (EBUSY). In diesem Fall wird die
    Temp-Datei im beschreibbaren tmp-Raum erzeugt und der vorbereitete,
    fsync-te Inhalt in-place in die gemountete Datei geschrieben. Der Lock
    `_SETTINGS_LOCK` schuetzt diesen Pfad vor parallelen Schreibern.
    """
    target = os.path.abspath(path)
    tdir = os.path.dirname(target) or "."
    os.makedirs(tdir, exist_ok=True)
    dir_writable = os.access(tdir, os.W_OK)
    temp_dir = tdir if dir_writable else tempfile.gettempdir()
    fd, tmp = tempfile.mkstemp(dir=temp_dir, prefix=".settings_", suffix=".tmp")
    try:
        # Letzten gueltigen Stand als .bak sichern, bevor ersetzt wird.
        # Nur moeglich, wenn das Zielverzeichnis beschreibbar ist.
        if dir_writable and os.path.exists(target):
            try:
                import shutil
                shutil.copy2(target, target + ".bak")
            except OSError as _exc:
                _archon_exc_logger.debug("[settings_json] Backup nicht moeglich: %s", _exc)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp, target)
        except OSError as exc:
            if exc.errno not in (errno.EBUSY, errno.EROFS, errno.EXDEV):
                raise
            with open(tmp, "r", encoding="utf-8") as src:
                content = src.read()
            with open(target, "r+", encoding="utf-8") as dst:
                dst.seek(0)
                dst.write(content)
                dst.truncate()
                dst.flush()
                os.fsync(dst.fileno())
            _archon_exc_logger.warning(
                "[settings_json] Ziel ist ein Bind-Mount (%s) - In-Place-Sync statt os.replace", target
            )
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError as _exc:
            _archon_exc_logger.debug("[settings_json] Ignorierte Ausnahme (Z.50): %s", _exc)
        raise
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


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
        data = loader() if loader is not None else _load_raw(path, strict=True)
        result = mutator(data)
        _write_atomic(path, data)
        return result


def load_settings(path: str) -> Dict[str, Any]:
    """Gelocktes, tolerantes Lesen (fuer konsistente Leser)."""
    with _SETTINGS_LOCK:
        return _load_raw(path)
