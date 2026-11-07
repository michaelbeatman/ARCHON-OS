"""P3: `GET /api/roles` von 2,6 MB entlasten (Materialisierung beim Lesen).

Gemessener Ist-Zustand (2026-11-07, agent_workspace/roles.json):
    2.630.808 B Datei, 59 Eintraege — davon 2.498.204 Zeichen `data:image…`
    in 5 Rollen, weil jedes Bild als `avatar` UND `avatar_url` drinsteht.
    Antwort von `GET /api/roles` vorher: 2.608.401 B, nachher 110.707 B.

Der Schnitt sitzt ausschliesslich in der Antwort: `roles.json` bleibt die
Quelle der Wahrheit (die data-URI bleibt in der Datei), jedes Bild wird einmalig
als Datei unter /static materialisiert und im Payload durch diesen Pfad ersetzt.
Beim **Schreiben** zu kuerzen waere falsch — fuer Rollen ohne eigenes Profil ist
die data-URI die einzige Kopie des Bildes.

Alle Schreibziele (Avatare) werden auf `tmp_path` umgebogen: der Test legt
nichts unter `static/avatars/` an und schreibt `roles.json` nie.
"""

import base64
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ARCHON_ROOT") or _HERE.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Die Rollendatei, die die App auf diesem Host liest (nur lesend verwendet).
ECHTE_ROLLENDATEI = ROOT / "agent_workspace" / "roles.json"

from archon.core import profiles as profiles_mod  # noqa: E402
from archon.core.cache import invalidate  # noqa: E402

import main as app_main  # noqa: E402

# Kleines, gueltiges 1x1-PNG (kein Bild aus dem Repo, keine Datei noetig).
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
)

# Schwelle aus dem Mandat: die Antwort muss deutlich unter 200 kB bleiben.
MAX_ANTWORT_BYTES = 200_000

AVATAR_FELDER = ("avatar", "avatar_url")
AVATAR_FELDER_SET = frozenset(AVATAR_FELDER)


def _png_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")


def _ist_data_uri(wert) -> bool:
    return isinstance(wert, str) and wert.startswith("data:image")


@pytest.fixture(scope="session")
def rohdaten():
    """Der Dateiinhalt, den die App tatsaechlich liest (nur gelesen)."""
    pfad = Path(app_main.ROLES_FILE)
    if not pfad.exists():  # pragma: no cover - Umgebung ohne Rollendatei
        pytest.skip(f"Rollendatei fehlt: {pfad}")
    return json.loads(pfad.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def antwort(tmp_path_factory):
    """Ein echter `GET /api/roles` ueber den TestClient.

    Avatare landen in einem Scratch-Verzeichnis, Auth ist aus (reiner Leser).
    """
    from fastapi.testclient import TestClient

    scratch = tmp_path_factory.mktemp("approot")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(profiles_mod, "APP_ROOT", str(scratch))
        mp.setattr(app_main.auth_service, "is_auth_enabled", lambda: False)
        invalidate(app_main.load_roles)
        resp = TestClient(app_main.app).get("/api/roles")
    invalidate(app_main.load_roles)

    assert resp.status_code == 200, resp.text[:400]
    body = resp.content  # httpx entpackt gzip bereits
    return {"body": body, "daten": json.loads(body), "scratch": scratch}


# --------------------------------------------------------------- Antwortgroesse

def test_api_roles_antwort_bleibt_unter_der_schwelle(antwort):
    """2,6 MB -> unter 200 kB, ohne dass ein Feld verschwindet."""
    groesse = len(antwort["body"])

    assert groesse < MAX_ANTWORT_BYTES, (
        f"GET /api/roles liefert {groesse} B (Schwelle {MAX_ANTWORT_BYTES} B) — "
        "die data:-URI-Avatare werden offenbar nicht materialisiert"
    )
    assert groesse > 0


def test_keine_data_uri_mehr_in_der_antwort(antwort):
    """Der Payload enthaelt kein eingebettetes Bild mehr."""
    offen = [
        (rolle.get("id"), feld)
        for rolle in antwort["daten"]
        for feld in AVATAR_FELDER
        if _ist_data_uri(rolle.get(feld))
    ]

    assert offen == [], f"noch als data:-URI in der Antwort: {offen}"


# --------------------------------------------------------- Gleichheitsnachweis

def test_alle_rollen_bleiben_vorhanden(antwort, rohdaten):
    """59/59: gleiche Anzahl, gleiche IDs, gleiche Reihenfolge."""
    erhalten = [r.get("id") for r in antwort["daten"]]
    erwartet = [r.get("id") for r in rohdaten]

    assert len(erhalten) == len(erwartet), f"{len(erhalten)} statt {len(erwartet)} Rollen"
    assert erhalten == erwartet
    assert set(erhalten) == set(erwartet)


def test_uebrige_felder_sind_byte_gleich(antwort, rohdaten):
    """Alles ausser avatar/avatar_url ist unveraendert (kanonisch verglichen)."""
    nach_id = {r.get("id"): r for r in antwort["daten"]}
    abweichungen = []

    for rolle in rohdaten:
        ziel = nach_id.get(rolle.get("id"))
        if ziel is None:
            abweichungen.append(f"{rolle.get('id')}: fehlt in der Antwort")
            continue
        rest_alt = {k: v for k, v in rolle.items() if k not in AVATAR_FELDER}
        rest_neu = {k: v for k, v in ziel.items() if k not in AVATAR_FELDER}
        dump_alt = json.dumps(rest_alt, sort_keys=True, ensure_ascii=False)
        dump_neu = json.dumps(rest_neu, sort_keys=True, ensure_ascii=False)
        if dump_alt != dump_neu:
            abweichungen.append(rolle.get("id"))

    assert abweichungen == [], f"Felder veraendert bei: {abweichungen}"
    # Kein Feld ist dazugekommen oder weggefallen.
    for rolle in rohdaten:
        assert set(nach_id[rolle["id"]]) - AVATAR_FELDER_SET == set(rolle) - AVATAR_FELDER_SET


def test_materialisiertes_bild_ist_byte_gleich_zur_data_uri(antwort, rohdaten):
    """SHA256(Datei unter /static) == SHA256(decodierte data-URI), je Rolle."""
    nach_id = {r.get("id"): r for r in antwort["daten"]}
    geprueft = 0

    for rolle in rohdaten:
        avatar = rolle.get("avatar")
        if not _ist_data_uri(avatar):
            continue
        _, b64 = avatar.split(",", 1)
        erwartet = hashlib.sha256(base64.b64decode(b64)).hexdigest()

        zurueck = nach_id[rolle["id"]]
        pfad = zurueck.get("avatar")
        assert isinstance(pfad, str) and pfad.startswith("/static/"), (
            f"{rolle['id']}: kein /static-Pfad in der Antwort ({pfad!r})"
        )
        datei = Path(antwort["scratch"]) / pfad.lstrip("/")
        assert datei.is_file(), f"{rolle['id']}: {datei} wurde nicht materialisiert"
        assert hashlib.sha256(datei.read_bytes()).hexdigest() == erwartet, (
            f"{rolle['id']}: Datei-Bytes weichen von der data-URI ab"
        )
        # API-Vertrag: das Frontend liest avatar_url — beide zeigen auf denselben Pfad.
        assert zurueck.get("avatar_url") == pfad
        geprueft += 1

    assert geprueft > 0, "keine data:-URI-Avatare in der Rollendatei gefunden"


def test_rolle_mit_nur_data_uri_in_einem_feld_bleibt_konsistent(antwort):
    """Wenn avatar eine data-URI war, ist avatar_url danach derselbe Pfad."""
    for rolle in antwort["daten"]:
        if rolle.get("avatar") is None and rolle.get("avatar_url") is None:
            continue
        assert rolle.get("avatar") == rolle.get("avatar_url") or not _ist_data_uri(
            rolle.get("avatar_url")
        )


# ----------------------------------------------------------- Quelle bleibt Quelle

def test_cached_rollen_behalten_die_data_uri(antwort):
    """`load_roles()` (Cache, interne Leser) wird nicht mutiert."""
    frisch = app_main.load_roles()
    data_uri_rollen = [
        r.get("id") for r in frisch
        if _ist_data_uri(r.get("avatar")) or _ist_data_uri(r.get("avatar_url"))
    ]

    assert data_uri_rollen, (
        "load_roles() liefert keine data:-URI mehr — die Antwort hat die "
        "gemeinsame Cache-Struktur veraendert (roles.json bleibt Quelle)"
    )


def test_zweiter_abruf_schreibt_nicht_neu(antwort, tmp_path_factory):
    """Der Helfer ist idempotent: unveraenderte Bytes -> kein Neuschreiben."""
    from fastapi.testclient import TestClient

    ziel = sorted((Path(antwort["scratch"]) / "static" / "avatars").glob("custom_*"))
    assert ziel, "keine materialisierten Avatare gefunden"
    vorher = {p.name: p.stat().st_mtime_ns for p in ziel}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(profiles_mod, "APP_ROOT", str(antwort["scratch"]))
        mp.setattr(app_main.auth_service, "is_auth_enabled", lambda: False)
        invalidate(app_main.load_roles)
        zweite = TestClient(app_main.app).get("/api/roles")
    invalidate(app_main.load_roles)

    assert zweite.status_code == 200
    nachher = {p.name: p.stat().st_mtime_ns for p in ziel}
    assert nachher == vorher, "zweiter Abruf hat Avatare neu geschrieben"


# ------------------------------------------------------------------ Fallback

@pytest.fixture()
def rollen_antwort(tmp_path, monkeypatch):
    """Baut eine Antwort aus einer synthetischen Rollenliste (ohne echte Datei)."""
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))

    def bauen(rollen):
        monkeypatch.setattr(app_main, "load_roles", lambda: rollen)
        return app_main.api_get_roles()

    return bauen


def test_none_fallback_behaelt_den_originalwert(rollen_antwort, monkeypatch):
    """Liefert der Helfer None (ungueltiger Wert), bleibt der Originalwert stehen."""
    monkeypatch.setattr(profiles_mod, "materialize_data_uri_avatar",
                        lambda *a, **k: None)
    wert = _png_data_uri()
    rollen = [{"id": "kaputt", "name": "K", "avatar": wert, "avatar_url": wert}]

    ergebnis = rollen_antwort(rollen)

    assert ergebnis[0]["avatar"] == wert
    assert ergebnis[0]["avatar_url"] == wert
    assert ergebnis[0]["avatar"] != ""


def test_unbrauchbarer_data_uri_wird_nicht_geleert(rollen_antwort):
    """Echter Helfer, kaputter Base64-Inhalt -> Originalwert, kein leeres Feld."""
    wert = "data:image/png;base64,!!!kein-base64!!!"
    rollen = [{"id": "halbkaputt", "avatar": wert, "avatar_url": wert}]

    ergebnis = rollen_antwort(rollen)

    for feld in AVATAR_FELDER:
        assert ergebnis[0][feld], f"{feld} wurde geleert"
        assert ergebnis[0][feld] == wert


def test_normale_avatar_urls_bleiben_unberuehrt(rollen_antwort):
    """Nicht-data:-Werte werden nicht angefasst (kein Schreibvorgang)."""
    rollen = [
        {"id": "url_rolle", "avatar": "/static/avatars/avatar_007.jpg",
         "avatar_url": "/static/avatars/avatar_007.jpg"},
        {"id": "leer", "avatar": "", "avatar_url": ""},
    ]

    ergebnis = rollen_antwort(rollen)

    assert ergebnis[0]["avatar"] == "/static/avatars/avatar_007.jpg"
    assert ergebnis[0]["avatar_url"] == "/static/avatars/avatar_007.jpg"
    assert ergebnis[1]["avatar"] == ""


def test_eingabe_wird_nicht_veraendert(rollen_antwort):
    """Die uebergebene (gecachte) Liste bleibt mit data-URI erhalten."""
    wert = _png_data_uri()
    rollen = [{"id": "cache_probe", "avatar": wert, "avatar_url": wert}]

    ergebnis = rollen_antwort(rollen)

    assert ergebnis[0]["avatar"] == "/static/avatars/custom_cache_probe.png"
    assert rollen[0]["avatar"] == wert, "die Eingabe wurde in-place veraendert"
    assert ergebnis is not rollen


# ======================================================================
# Nachtrag: Rundlauf-Schutz in save_roles (GET -> POST -> roles.json)
# ======================================================================
#
# `GET /api/roles` liefert materialisierte /static-Pfade, das Frontend postet
# die Antwort unveraendert zurueck. Ohne Ruecknormalisierung stuenden die Pfade
# in der Datei und die data-URI — fuer Rollen ohne Profil die einzige Kopie des
# Bildes — waere nach dem ersten Speichern im UI verloren.

JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-nur-fuer-den-rundlauf"


def _jpeg_data_uri() -> str:
    return "data:image/jpeg;base64," + base64.b64encode(JPEG_BYTES).decode("ascii")


def _sha256_von_data_uri(wert: str) -> str:
    _, b64 = wert.split(",", 1)
    return hashlib.sha256(base64.b64decode(b64)).hexdigest()


def _rundlauf_rollen() -> list:
    """Zwei Rollen mit data:-URI (wie die echten 5) und eine mit normaler URL."""
    png = _png_data_uri()
    jpeg = _jpeg_data_uri()
    return [
        {"id": "rolle_png", "name": "PNG", "avatar": png, "avatar_url": png},
        {"id": "rolle_jpeg", "name": "JPEG", "avatar": jpeg, "avatar_url": jpeg},
        {"id": "rolle_url", "name": "URL", "avatar": "https://example.invalid/a.png",
         "avatar_url": "https://example.invalid/a.png"},
    ]


@pytest.fixture()
def rundlauf(tmp_path, monkeypatch):
    """TestClient mit Rollendatei UND Avatar-Ziel in tmp_path (kein Repo-Schreiben)."""
    from fastapi.testclient import TestClient

    approot = tmp_path / "approot"
    (approot / "static" / "avatars").mkdir(parents=True)
    roles_file = tmp_path / "roles.json"
    roles_file.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(approot))
    monkeypatch.setattr(app_main, "ROLES_FILE", str(roles_file))
    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: False)
    # RBAC ist nicht Gegenstand dieses Tests (eigene Datei: test_rbac_*).
    monkeypatch.setattr(app_main, "require_admin", lambda request: {"role": "admin"})
    invalidate(app_main.load_roles)

    lauf = {"client": TestClient(app_main.app), "roles_file": roles_file,
            "approot": approot}
    yield lauf
    invalidate(app_main.load_roles)


def _post_antwort(lauf, antwort):
    """Postet den GET-Body unveraendert zurueck — genau wie das Frontend."""
    return lauf["client"].post(
        "/api/roles", content=antwort.content,
        headers={"Content-Type": "application/json"},
    )


def test_rundlauf_schreibt_data_uris_zurueck(rundlauf):
    """GET -> POST unveraendert -> in der Datei stehen wieder die data-URIs."""
    original = _rundlauf_rollen()
    rundlauf["roles_file"].write_text(json.dumps(original), encoding="utf-8")
    invalidate(app_main.load_roles)

    erste = rundlauf["client"].get("/api/roles")
    assert erste.status_code == 200
    assert b"data:image" not in erste.content, "GET liefert noch data-URIs"

    gespeichert = _post_antwort(rundlauf, erste)
    assert gespeichert.status_code == 200, gespeichert.text

    in_datei = rundlauf["roles_file"].read_text(encoding="utf-8")
    assert "/static/avatars/" not in in_datei, (
        "der Rundlauf hat die materialisierten Pfade in roles.json geschrieben"
    )
    daten = {r["id"]: r for r in json.loads(in_datei)}
    for rolle in original:
        if not _ist_data_uri(rolle["avatar"]):
            continue
        erwartet = _sha256_von_data_uri(rolle["avatar"])
        for feld in AVATAR_FELDER:
            wert = daten[rolle["id"]][feld]
            assert _ist_data_uri(wert), f"{rolle['id']}.{feld}: keine data-URI mehr"
            assert _sha256_von_data_uri(wert) == erwartet, (
                f"{rolle['id']}.{feld}: Bildbytes weichen vom Original ab"
            )


def test_zweiter_rundlauf_ist_idempotent(rundlauf):
    """Zweimal GET -> POST: identischer Dateiinhalt, kein Wachstum."""
    rundlauf["roles_file"].write_text(json.dumps(_rundlauf_rollen()), encoding="utf-8")
    invalidate(app_main.load_roles)

    erste = rundlauf["client"].get("/api/roles")
    assert _post_antwort(rundlauf, erste).status_code == 200
    datei_nach_1 = rundlauf["roles_file"].read_bytes()
    laenge_nach_1 = len(erste.content)

    zweite = rundlauf["client"].get("/api/roles")
    assert _post_antwort(rundlauf, zweite).status_code == 200
    datei_nach_2 = rundlauf["roles_file"].read_bytes()

    assert datei_nach_2 == datei_nach_1, "zweiter Rundlauf hat die Datei veraendert"
    assert len(zweite.content) == laenge_nach_1, (
        f"Antwortgroesse waechst im Rundlauf: {laenge_nach_1} -> {len(zweite.content)} B"
    )
    assert datei_nach_2.count(b"data:image") == 4, "data-URI doppelt oder verloren"


def test_antwortgroesse_bleibt_nach_rundlauf_klein(rundlauf):
    """Kein Rueckfall auf 2,6 MB: die Antwort bleibt unter der Schwelle."""
    rundlauf["roles_file"].write_text(json.dumps(_rundlauf_rollen()), encoding="utf-8")
    invalidate(app_main.load_roles)

    erste = rundlauf["client"].get("/api/roles")
    _post_antwort(rundlauf, erste)
    zweite = rundlauf["client"].get("/api/roles")

    assert len(zweite.content) < MAX_ANTWORT_BYTES
    assert len(zweite.content) == len(erste.content)


def test_gespeicherte_data_uri_wird_zurueckgewandelt(rundlauf):
    """Der Rueckweg greift genau fuer den Pfad, den GET aus dem data-URI macht."""
    wert = _png_data_uri()
    rundlauf["roles_file"].write_text(
        json.dumps([{"id": "probe", "avatar": wert, "avatar_url": wert}]),
        encoding="utf-8")
    invalidate(app_main.load_roles)

    antwort = rundlauf["client"].get("/api/roles")
    pfad = antwort.json()[0]["avatar"]
    assert pfad == "/static/avatars/custom_probe.png"

    app_main.save_roles([{"id": "probe", "avatar": pfad, "avatar_url": pfad}])

    gespeichert = json.loads(rundlauf["roles_file"].read_text(encoding="utf-8"))[0]
    for feld in AVATAR_FELDER:
        assert gespeichert[feld] == wert, f"{feld}: kein Rueckweg"
    assert base64.b64decode(gespeichert["avatar"].split(",", 1)[1]) == PNG_BYTES


def test_bestehender_static_pfad_bleibt_pfad(rundlauf):
    """Verschaeft: ein schon gespeicherter /static-Pfad wird NICHT eingebettet.

    Sonst bliese ein Speichern die Datei um die Bytes aller Katalog-Avatare auf.
    """
    pfad = "/static/avatars/avatar_001.jpg"
    (rundlauf["approot"] / "static" / "avatars" / "avatar_001.jpg").write_bytes(JPEG_BYTES)
    rundlauf["roles_file"].write_text(
        json.dumps([{"id": "katalog", "avatar": pfad, "avatar_url": pfad}]),
        encoding="utf-8")
    invalidate(app_main.load_roles)

    app_main.save_roles([{"id": "katalog", "avatar": pfad, "avatar_url": pfad}])

    in_datei = rundlauf["roles_file"].read_text(encoding="utf-8")
    assert "data:image" not in in_datei, "alter /static-Pfad wurde zur data-URI gemacht"
    gespeichert = json.loads(in_datei)[0]
    for feld in AVATAR_FELDER:
        assert gespeichert[feld] == pfad


def test_rundlauf_mit_echter_rollendatei_waechst_nicht(rundlauf):
    """Realistische Groesse: Kopie der echten roles.json darf max. 1 % wachsen."""
    if not ECHTE_ROLLENDATEI.is_file():  # pragma: no cover - Umgebung ohne Datei
        pytest.skip(f"Rollendatei fehlt: {ECHTE_ROLLENDATEI}")
    original = ECHTE_ROLLENDATEI.read_bytes()
    shutil.copyfile(ECHTE_ROLLENDATEI, rundlauf["roles_file"])
    invalidate(app_main.load_roles)

    erste = rundlauf["client"].get("/api/roles")
    assert erste.status_code == 200
    assert _post_antwort(rundlauf, erste).status_code == 200

    neue_laenge = rundlauf["roles_file"].stat().st_size
    assert neue_laenge <= len(original) * 1.01, (
        f"roles.json waechst von {len(original)} B auf {neue_laenge} B"
    )
    neu = rundlauf["roles_file"].read_bytes()
    assert neu.count(b"/static/avatars/") == original.count(b"/static/avatars/"), (
        "die bestehenden /static-Pfade wurden angefasst"
    )
    assert neu.count(b"data:image") == original.count(b"data:image")


@pytest.mark.parametrize("wert", [
    "https://example.invalid/a.png",
    "/static/avatars/gibt_es_nicht.png",              # Datei fehlt
    "/static/avatars/custom_probe.txt",               # Endung unbekannt (Datei existiert)
    "/static/avatars/../../etc/passwd",               # Pfad-Ausbruch
    "/static/avatars/custom_probe.png?v=1792619",     # Abfrage-Parameter
    "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii"),
    "",
], ids=["http", "datei-fehlt", "endung-unbekannt", "traversal", "query", "data-uri", "leer"])
def test_nicht_umkehrbare_werte_bleiben_stehen(rundlauf, wert):
    """Kein Erfinden, kein Leeren, kein Lesen ausserhalb von static/avatars."""
    (rundlauf["approot"] / "static" / "avatars" / "custom_probe.txt").write_bytes(b"x")
    (rundlauf["approot"] / "static" / "avatars" / "custom_probe.png").write_bytes(PNG_BYTES)
    # Vorlage = derselbe Wert: der gespeicherte Stand gibt keinen data-URI her.
    rundlauf["roles_file"].write_text(
        json.dumps([{"id": "roh", "avatar": wert, "avatar_url": wert}]), encoding="utf-8")
    invalidate(app_main.load_roles)

    app_main.save_roles([{"id": "roh", "avatar": wert, "avatar_url": wert}])

    gespeichert = json.loads(rundlauf["roles_file"].read_text(encoding="utf-8"))[0]
    for feld in AVATAR_FELDER:
        assert gespeichert[feld] == wert, f"{feld}: Wert wurde veraendert oder geleert"


def test_save_roles_gibt_die_eingabe_nicht_zurueck_veraendert(rundlauf):
    """Die uebergebene Liste bleibt unberuehrt (der Aufrufer haelt sie weiter)."""
    wert = _png_data_uri()
    (rundlauf["approot"] / "static" / "avatars" / "custom_probe.png").write_bytes(PNG_BYTES)
    rundlauf["roles_file"].write_text(
        json.dumps([{"id": "probe", "avatar": wert, "avatar_url": wert}]), encoding="utf-8")
    invalidate(app_main.load_roles)
    rollen = [{"id": "probe", "avatar": "/static/avatars/custom_probe.png",
               "avatar_url": "/static/avatars/custom_probe.png"}]

    app_main.save_roles(rollen)

    assert rollen[0]["avatar"] == "/static/avatars/custom_probe.png"
    assert _ist_data_uri(json.loads(rundlauf["roles_file"].read_text(encoding="utf-8"))[0]["avatar"])
