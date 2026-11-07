"""Sicherheits-Haertung der drei Triage-Routen (Paket „Triage 9 → 3").

Geprueft werden genau diese Routen:

    POST   /api/v1/library/upload      (Upload-RCE: `filename` mit `../..`)
    DELETE /api/vault?path=…           (Reichweite bis ~/.hermes)
    POST   /api/telegram/voice-relay   (beliebige chat_id mit Bot-Credentials)

Je Route:

    Rolle viewer/operator        -> 403 und **kein** Seiteneffekt
    Rolle admin                  -> Erfolgspfad (Ziele in tmp_path)
    X-Archon-Service-Token       -> wie admin (Adapter bleibt drin)

Dazu die fachlichen Nachweise: `../../evil.py` landet als `evil.py` *innerhalb*
von raw_dir, `~/.hermes/config.yaml` ergibt 403 (Datei bleibt), eine Vault-Datei
wird geloescht, `chat_id="abc"` ergibt 400 ohne Sendung, und ein Fehlertext
enthaelt weder Bot-Token noch Bot-API-URL.

Alles laeuft ueber ``TestClient`` gegen das App-Objekt im Prozess; jede
Fachfunktion ist ersetzt, es geht kein Netzaufruf und kein Telegram-Versand raus.
"""

import os
import sys
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADMIN = {"id": "usr_admin", "username": "admin", "role": "admin", "permissions": {}}
VIEWER = {"id": "usr_vw", "username": "max", "role": "viewer", "permissions": {}}

UPLOAD_PATH = "/api/v1/library/upload"
VAULT_PATH = "/api/vault"
VOICE_PATH = "/api/telegram/voice-relay"


def _app():
    import main  # noqa: PLC0415  (spaeter Import: ~1 s Modulaufbau)
    return main


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(_app().app)


def _call(client, method, path, *, user=None, auth_enabled=True,
          service_token=None, **kwargs):
    """Ein Request mit gesteuerter Identitaet (Session bzw. Service-Token)."""
    m = _app()
    headers = dict(kwargs.pop("headers", None) or {})
    if user is not None:
        headers["Authorization"] = "Bearer tok_test"
    if service_token is not None:
        headers["X-Archon-Service-Token"] = service_token
    with patch.object(m.auth_service, "is_auth_enabled", return_value=auth_enabled), \
            patch.object(m.auth_service, "verify_session", return_value=user):
        return client.request(method, path, headers=headers, **kwargs)


# --------------------------------------------------- Auth-Gate (anon = 401)

@pytest.mark.parametrize("method,path", [("POST", UPLOAD_PATH),
                                         ("DELETE", VAULT_PATH),
                                         ("POST", VOICE_PATH)],
                         ids=["upload", "vault-delete", "voice-relay"])
def test_anonymous_is_blocked_by_auth_gate(client, method, path):
    """Ohne Session und ohne Service-Token greift der globale Gate (401)."""
    r = _call(client, method, path)
    assert r.status_code == 401, f"{path}: erwartet 401, bekam {r.status_code}: {r.text}"


# --------------------------------------------------------------- Upload (A)

@pytest.fixture()
def upload_env(tmp_path, monkeypatch):
    """Bibliotheks-Ziele in tmp_path; Ingest und RAG-Sync bleiben Attrappen."""
    import utils.batch_library_importer as importer

    raw_dir = tmp_path / "raw_docs"
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    ingest_calls = []

    def _fake_process(file_path, vault_dir_arg, target_category="auto"):
        ingest_calls.append(file_path)
        return {"status": "ok"}

    monkeypatch.setattr(importer, "resolve_raw_docs_dir", lambda: str(raw_dir))
    monkeypatch.setattr(importer, "resolve_vault_path", lambda: str(vault_dir))
    monkeypatch.setattr(importer, "process_document", _fake_process)
    return {"raw_dir": raw_dir, "vault_dir": vault_dir, "ingest_calls": ingest_calls}


def test_upload_viewer_forbidden_without_side_effect(client, upload_env):
    r = _call(client, "POST", UPLOAD_PATH, user=VIEWER,
              files={"files": ("notiz.txt", b"inhalt")},
              data={"auto_ingest": "false"})

    assert r.status_code == 403, f"erwartet 403, bekam {r.status_code}: {r.text}"
    assert "Administratoren" in r.json().get("detail", ""), r.text
    assert not upload_env["raw_dir"].exists(), "raw_dir wurde trotz 403 angelegt"
    assert upload_env["ingest_calls"] == []


def test_upload_admin_writes_inside_raw_dir(client, upload_env):
    r = _call(client, "POST", UPLOAD_PATH, user=ADMIN,
              files={"files": ("notiz.txt", b"inhalt")},
              data={"auto_ingest": "false"})

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    ziel = upload_env["raw_dir"] / "notiz.txt"
    assert ziel.is_file() and ziel.read_bytes() == b"inhalt"
    assert r.json()["items"][0]["filename"] == "notiz.txt"


def test_upload_traversal_lands_as_basename_inside_raw_dir(client, upload_env):
    """`../../evil.py` darf nicht aus raw_dir herausfuehren."""
    r = _call(client, "POST", UPLOAD_PATH, user=ADMIN,
              files={"files": ("../../evil.py", b"payload")},
              data={"auto_ingest": "false"})

    raw_dir = upload_env["raw_dir"]
    drin = raw_dir / "evil.py"
    draussen = [p for p in (raw_dir.parent / "evil.py", raw_dir.parent.parent / "evil.py")
                if p.exists()]

    assert r.status_code in (200, 400), f"{r.status_code}: {r.text}"
    if r.status_code == 200:
        assert drin.is_file(), "Datei landete nicht (umbenannt) in raw_dir"
        assert r.json()["items"][0]["filename"] == "evil.py"
    assert not draussen, f"Datei ausserhalb raw_dir geschrieben: {draussen}"
    assert not (raw_dir.parent / "evil.py").exists()
    assert not (raw_dir.parent.parent / "evil.py").exists()


def test_upload_service_token_passes(client, upload_env):
    m = _app()
    with patch.object(m, "_get_service_token", return_value="tok-service-test"):
        r = _call(client, "POST", UPLOAD_PATH, service_token="tok-service-test",
                  files={"files": ("dienst.txt", b"x")},
                  data={"auto_ingest": "false"})

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert (upload_env["raw_dir"] / "dienst.txt").is_file()


# ---------------------------------------------------------------- Vault (B)

@pytest.fixture()
def vault_env(tmp_path, monkeypatch):
    """Vault-Wurzel in tmp_path und ein gefaktes HOME fuer ~/.hermes."""
    m = _app()
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    note = vault_dir / "notiz.md"
    note.write_text("inhalt", encoding="utf-8")

    fake_home = tmp_path / "home"
    (fake_home / ".hermes").mkdir(parents=True)
    config = fake_home / ".hermes" / "config.yaml"
    config.write_text("secret_paths: []\n", encoding="utf-8")

    monkeypatch.setattr(m, "OBSIDIAN_VAULT_DIR", str(vault_dir))
    monkeypatch.setenv("HOME", str(fake_home))
    return {"vault_dir": vault_dir, "note": note, "config": config}


def test_vault_delete_viewer_forbidden_without_side_effect(client, vault_env):
    r = _call(client, "DELETE", VAULT_PATH, user=VIEWER,
              params={"path": str(vault_env["note"])})

    assert r.status_code == 403, f"erwartet 403, bekam {r.status_code}: {r.text}"
    assert "Administratoren" in r.json().get("detail", ""), (
        f"403 kommt nicht vom Rollenzaun: {r.text}"
    )
    assert vault_env["note"].is_file(), "Vault-Datei wurde trotz 403 geloescht"


def test_vault_delete_blocks_hermes_path(client, vault_env):
    """`~/.hermes/config.yaml` liegt im Jail, aber NICHT in der Vault-Wurzel."""
    r = _call(client, "DELETE", VAULT_PATH, user=ADMIN,
              params={"path": "~/.hermes/config.yaml"})

    assert r.status_code == 403, f"erwartet 403, bekam {r.status_code}: {r.text}"
    assert vault_env["config"].is_file(), "Hermes-Config wurde geloescht!"


def test_vault_delete_admin_removes_vault_file(client, vault_env):
    r = _call(client, "DELETE", VAULT_PATH, user=ADMIN,
              params={"path": str(vault_env["note"])})

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert r.json()["status"] == "success"
    assert r.json()["deleted"] == str(vault_env["note"])
    assert not vault_env["note"].exists()


def test_vault_delete_service_token_passes(client, vault_env):
    m = _app()
    with patch.object(m, "_get_service_token", return_value="tok-service-test"):
        r = _call(client, "DELETE", VAULT_PATH, service_token="tok-service-test",
                  params={"path": str(vault_env["note"])})

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert not vault_env["note"].exists()


# ---------------------------------------------------------- Voice-Relay (C)

@pytest.fixture()
def voice_spies(tmp_path, monkeypatch):
    """Ersetzt alle Seiteneffekte der Route; sammelt Aufrufe."""
    import backend.voice_pipeline as vp

    calls = {"transcribe": 0, "send_voice": [], "synth": 0}
    speech = tmp_path / "antwort.mp3"
    speech.write_bytes(b"ID3")

    async def _transcribe(data, filename="audio.ogg", language="de"):
        calls["transcribe"] += 1
        return "/robert bitte Status"

    def _detect(transcript):
        return "robert", "bitte Status"

    async def _synth(text, output_path=None, voice=None):
        calls["synth"] += 1
        return str(speech)

    async def _send_voice(chat_id, audio_path, caption=None, bot_token=None):
        calls["send_voice"].append(chat_id)
        return True

    async def _download(file_id, bot_token=None):
        return b"OggS", "voice.ogg"

    monkeypatch.setattr(vp, "transcribe_audio_bytes", _transcribe)
    monkeypatch.setattr(vp, "detect_target_agent", _detect)
    monkeypatch.setattr(vp, "synthesize_speech", _synth)
    monkeypatch.setattr(vp, "send_telegram_voice", _send_voice)
    monkeypatch.setattr(vp, "download_telegram_file", _download)
    return calls


@pytest.fixture()
def relay_stub(monkeypatch):
    """Der interne Relay-Aufruf wird nicht ausgefuehrt (kein Dispatch, kein LLM)."""
    m = _app()
    relay_calls = []

    async def _fake_relay(ziel_agent="", text="", datei_name="", datei_b64=""):
        relay_calls.append((ziel_agent, text))
        return {"status": "ok", "antwort_kopf": "Antwort des Agenten"}

    monkeypatch.setattr(m, "api_telegram_relay", _fake_relay)
    return relay_calls


def test_voice_relay_viewer_forbidden_without_send(client, voice_spies, relay_stub):
    r = _call(client, "POST", VOICE_PATH, user=VIEWER,
              files={"file": ("voice.ogg", b"OggS")},
              data={"chat_id": "123456789"})

    assert r.status_code == 403, f"erwartet 403, bekam {r.status_code}: {r.text}"
    assert voice_spies["transcribe"] == 0, "Transkription lief trotz 403"
    assert voice_spies["send_voice"] == [], "Telegram-Versand lief trotz 403"
    assert relay_stub == [], "Agenten-Relay lief trotz 403"


def test_voice_relay_invalid_chat_id_is_400_without_send(client, voice_spies, relay_stub):
    r = _call(client, "POST", VOICE_PATH, user=ADMIN,
              files={"file": ("voice.ogg", b"OggS")},
              data={"chat_id": "abc"})

    assert r.status_code == 400, f"erwartet 400, bekam {r.status_code}: {r.text}"
    assert "chat_id" in r.json().get("detail", ""), r.text
    assert voice_spies["send_voice"] == [], "Es wurde trotz ungueltiger chat_id gesendet"
    assert voice_spies["transcribe"] == 0, "Transkribiert, bevor chat_id geprueft war"
    assert relay_stub == []


def test_voice_relay_admin_sends_to_given_chat(client, voice_spies, relay_stub):
    r = _call(client, "POST", VOICE_PATH, user=ADMIN,
              files={"file": ("voice.ogg", b"OggS")},
              data={"chat_id": "-1001234567890", "reply_voice": "true"})

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert r.json()["voice_sent"] is True
    assert voice_spies["send_voice"] == ["-1001234567890"], voice_spies["send_voice"]
    assert relay_stub and relay_stub[0][0] == "robert"


def test_voice_relay_service_token_passes(client, voice_spies, relay_stub):
    m = _app()
    with patch.object(m, "_get_service_token", return_value="tok-service-test"):
        r = _call(client, "POST", VOICE_PATH, service_token="tok-service-test",
                  files={"file": ("voice.ogg", b"OggS")},
                  data={"chat_id": "123456789", "reply_voice": "true"})

    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert voice_spies["send_voice"] == ["123456789"]


def test_voice_relay_error_detail_contains_no_credentials(client, voice_spies, relay_stub):
    """Fehlertext darf weder Bot-Token noch Bot-API-URL enthalten."""
    import backend.voice_pipeline as vp

    token = "123456789:AAFakeBotTokenDoNotLeak1234567890"
    boom = RuntimeError(f"connect failed for https://api.telegram.org/bot{token}/getFile?file_id=x")

    async def _download_fail(file_id, bot_token=None):
        raise boom

    m = _app()
    with patch.object(vp, "download_telegram_file", _download_fail):
        r = _call(client, "POST", VOICE_PATH, user=ADMIN,
                  data={"file_id": "abc", "chat_id": "123456789"})

    assert r.status_code == 400, f"{r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert token not in detail, "Bot-Token steht in der Antwort"
    assert "AAFakeBotToken" not in detail, "Token-Fragment steht in der Antwort"
    assert "api.telegram.org" not in detail, "Bot-API-URL steht in der Antwort"
    assert "Download von Telegram fehlgeschlagen" in detail, detail

    # Log-Pfad derselben Route ebenfalls redigiert (gleiche Funktion im Einsatz).
    redigiert = m._redact_telegram_secrets(boom)
    assert token not in redigiert and "api.telegram.org" not in redigiert
