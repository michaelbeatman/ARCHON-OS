#!/usr/bin/env python3
"""OmniRoute-Healthcheck für die Free-Tier-Combo.

Prüft jedes Modell der Combo `strict-free-tier-combo` mit einem echten Mini-Call
(genug Tokens, damit Reasoning-Modelle nicht in die Quality-Validation laufen).
Standard: nur prüfen und bei Totalausfall per Telegram alarmieren.

  --fix     tote Modelle durch verifizierte freie Modelle ersetzen (Neustart nötig)
  --json    maschinenlesbare Ausgabe

Hintergrund: Die Combo bestand aus sechs Modellen, die Google/OpenRouter
abgeschaltet haben (Gemini 2.0 → 402, drei :free-Slugs → 404). Jeder auto/*-Alias
zeigte darauf, damit war der komplette Router funktionslos.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "omniroute_data", "data", "storage.sqlite")
ENV_FILE = os.path.join(ROOT, ".env")
COMBO = "strict-free-tier-combo"
API = "http://localhost:20128/v1/chat/completions"


def _env(key: str, default: str = "") -> str:
    if not os.path.exists(ENV_FILE):
        return default
    for line in open(ENV_FILE, encoding="utf-8", errors="ignore"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


def combo_models(name: str = COMBO):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = con.execute("select data from combos where name = ?", (name,)).fetchone()
    finally:
        con.close()
    if not row:
        return []
    return [m["model"] for m in json.loads(row[0]).get("models", [])]


def ping(model: str, key: str, timeout: int = 60):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Antworte mit genau: OK"}],
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        latency = int((time.time() - start) * 1000)
        if "error" in body:
            return False, str(body["error"].get("message", ""))[:160], latency
        content = str(body.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        return bool(content), content[:40] or "(leer)", latency
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read(300).decode('utf-8', 'replace')[:120]}", 0
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:140], 0


def notify(text: str):
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[warn] Telegram nicht konfiguriert")
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15)
        print("[ok] Telegram-Alarm gesendet")
    except Exception as e:
        print(f"[warn] Telegram-Fehler: {e}")


def candidates(key: str, exclude):
    """Freie OpenRouter-Modelle, die laut /models keine Kosten haben."""
    req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                                 headers={"Authorization": f"Bearer {key}"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode()).get("data", [])
    free = []
    for m in data:
        mid = m.get("id", "")
        if not mid.endswith(":free") or mid in exclude:
            continue
        p = m.get("pricing", {})
        if float(p.get("prompt", 1)) == 0.0 and float(p.get("completion", 1)) == 0.0:
            free.append(mid)
    return free


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    key = _env("OMNIROUTE_API_KEY")
    if not key:
        print("FEHLER: OMNIROUTE_API_KEY fehlt in .env")
        return 2

    models = combo_models()
    results = []
    for m in models:
        ok, detail, ms = ping(m, key)
        results.append({"model": m, "ok": ok, "detail": detail, "ms": ms})
        if not args.json:
            print(f"{'OK ' if ok else 'TOT'}  {m:<58} {ms:>5}ms  {detail}")

    alive = [r for r in results if r["ok"]]
    dead = [r for r in results if not r["ok"]]

    if args.json:
        print(json.dumps({"alive": len(alive), "dead": len(dead), "results": results}, indent=2, ensure_ascii=False))
        return 0 if alive else 1

    if dead:
        notify(
            "⚠️ *OmniRoute-Wächter*\n"
            f"{len(dead)} von {len(models)} Combo-Modellen antworten nicht:\n"
            + "\n".join(f"• `{r['model']}`: {r['detail'][:80]}" for r in dead)
            + ("\n\nRouter läuft weiter über die verbleibenden Modelle." if alive else
               "\n\n*Kein Modell erreichbar — auto/* ist ausgefallen.*")
        )

    if args.fix and dead:
        print("\n--fix: suche lebende freie Modelle ...")
        pool = [m for m in candidates(key, set(models)) if model_alive(m, key)]
        print("Kandidaten:", pool[:5])
        if pool:
            new_models = [m for m in models if m in [a["model"] for a in alive]] + pool[:3]
            replace_combo(new_models)
            print("Combo aktualisiert:", new_models)
        else:
            print("Keine lebenden Kandidaten gefunden.")

    return 0 if alive else 1


def model_alive(model: str, key: str) -> bool:
    ok, _, _ = ping(model, key, timeout=45)
    return ok


def replace_combo(new_models):
    subprocess.run(["docker", "stop", "omniroute"], check=True, capture_output=True)
    con = sqlite3.connect(DB)
    try:
        row = con.execute("select data from combos where name = ?", (COMBO,)).fetchone()
        data = json.loads(row[0])
        data["models"] = [{"model": m, "weight": 0} for m in new_models]
        con.execute("update combos set data = ?, updated_at = ? where name = ?",
                    (json.dumps(data, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%S.000Z"), COMBO))
        con.commit()
    finally:
        con.close()
    subprocess.run(["docker", "start", "omniroute"], check=True, capture_output=True)
    time.sleep(8)


if __name__ == "__main__":
    import urllib.parse  # noqa: E402 (für notify)
    sys.exit(main())
