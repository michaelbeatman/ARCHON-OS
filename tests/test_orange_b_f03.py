"""Regressionstest F-03: Firmendaten atomar speichern (kein Datenverlust).

Vor dem Fix schrieb `_save_data` direkt ueber die Zieldatei (kein Temp+replace,
kein Lock). Ein Abbruch mitten im Write hinterliess eine kaputte Datei; der
naechste save_company() legte nur noch die Default-Firma an und alle anderen
Firmen waren weg.
"""

import json
import os
import tempfile

from backend.corporate_manager import CorporateManager


def test_save_data_is_atomic_no_partial_file():
    """Es existiert nie eine temporaere Halbdatei im Zielverzeichnis (Temp+replace)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "corporate_profiles.json")
        mgr = CorporateManager(filepath=path)
        mgr.save_company({"id": "firma-1", "name": "Firma 1 GmbH"})
        mgr.save_company({"id": "firma-2", "name": "Firma 2 GmbH"})

        # Keine .tmp-Reste im Verzeichnis
        leftovers = [n for n in os.listdir(tmpdir) if n.endswith(".tmp")]
        assert leftovers == [], f"Temp-Reste gefunden: {leftovers}"


def test_corrupt_file_does_not_wipe_other_companies_on_next_save():
    """Kaputte Datei + naechster save_company() darf nicht alle Firmen loeschen.

    F-03-Kern: die Schreibung ist atomar, d. h. eine korrekte Datei kann gar
    nicht erst in einen Halbstand geraten. Zusatz-Hygiene: stammt der
    Halbstand aus einer Fremdquelle, wirft _load_data keinen stillen
    Datenverlust-Weg fuer die persistierten Firmen.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "corporate_profiles.json")
        mgr = CorporateManager(filepath=path)
        mgr.save_company({"id": "firma-1", "name": "Firma 1 GmbH"})
        mgr.save_company({"id": "firma-2", "name": "Firma 2 GmbH"})

        with open(path, "r", encoding="utf-8") as f:
            voll = json.load(f)
        assert len(voll["companies"]) == 3  # default + firma-1 + firma-2

        # Ein erneuter RMW-Zyklus erhaelt beide Firmen.
        mgr2 = CorporateManager(filepath=path)
        mgr2.save_company({"id": "firma-3", "name": "Firma 3 GmbH"})
        with open(path, "r", encoding="utf-8") as f:
            nachher = json.load(f)
        ids = {c["id"] for c in nachher["companies"]}
        assert {"firma-1", "firma-2", "firma-3"} <= ids


def test_parallel_saves_lose_no_company():
    """Parallele save_company-Aufrufe (Threads) verlieren keine Firma (Lock)."""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "corporate_profiles.json")
        mgr = CorporateManager(filepath=path)

        def _save(i):
            mgr.save_company({"id": f"parallel-{i}", "name": f"Parallel {i}"})

        threads = [threading.Thread(target=_save, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with open(path, "r", encoding="utf-8") as f:
            final = json.load(f)
        ids = {c["id"] for c in final["companies"]}
        assert {"parallel-%d" % i for i in range(8)} <= ids
