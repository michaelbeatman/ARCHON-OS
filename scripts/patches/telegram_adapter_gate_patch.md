# Telegram-Adapter-Patch: Archon-Callbacks im Hermes-Adapter (Stand 12.10.2026, robust)

**Zweck:** Die Inline-Buttons aus Archon im Hermes-Telegram-Adapter verarbeiten:
- `gate:approve:<gate_id>` / `gate:reject:<gate_id>` -> `POST /api/permission-gates/<id>/decide`
- `app:details|approve|reject:<ref_id>` -> Kanban-/Mission-Control-API

Mit Owner-Autorisierung, sofortiger `query.answer()`-Quittung (Toast unter dem Knopf)
und **retry-festem HTTP** gegen ARCHON-OS.

**Datei:** `/opt/hermes/plugins/platforms/telegram/adapter.py`
- Helper `_archon_req` eingefuegt in `_handle_callback_query` direkt NACH
  `query_user_name = getattr(query.from_user, "first_name", None)`.
- `gate:`-Zweig VOR `# --- Model picker callbacks ---`.
- `app:`-Zweig nutzt denselben Helper (vorher 4x `async with _httpx.AsyncClient(...)`).

**Warum gesichert:** `/opt/hermes` ist IMAGE-LAYER. Aeltere Patches (`app:*` vom
09.10.) sind bei einem Hermes-Image-Update schon einmal VERSCHWUNDEN. Nach jedem
Hermes-Image-Update diesen Patch ERNEUT anwenden (Rezept unten).

## Aenderung 12.10.2026 (Robustheit, User-Entscheidung)

Beobachteter Fehler: ein Owner-Klick auf OK erzeugte
`ERROR ... [Telegram] Gate-Callback an ARCHON fehlgeschlagen:` mit **leerer**
Fehlermeldung (`httpx.ConnectError`), waehrend ein anderer Klick im selben
Fenster **erfolgreich** war (Gate approved, Profil gespeichert). Ursache ist ein
**transienter Container-DNS-/Connect-Fehler** im Hochlast-Fenster (loadavg 37,
Gateway-SIGKILLs), **kein Auth-Bug** - Auth (`_is_callback_user_authorized`) greift durch.

Gegenmaßnahme: `_archon_req` = 3 Versuche mit Backoff (0.5/1.0 s), danach EIN
Notfallversuch gegen die frisch per DNS aufgeloeste IP (`gethostbyname`). Nicht
britt - der Hostname bleibt erste Wahl, die IP wird erst im Notfall bestimmt.
Maschinell geprueft (gleiche Algorithmik im Container): Gutfall = 1 Versuch,
nicht aufloesbarer Host = 3 Retries + IP-Pfad.

**DNS-Befund (kein Code):** hermes nutzt `/etc/resolv.conf` -> `nameserver 127.0.0.11`
(Docker-embedded), ExtServers `8.8.8.8 1.1.1.1`. Stand jetzt stabil
(20/20 Aufloesungen, 30/30 HTTP 200 gegen `ARCHON-OS`). Externe Lookups
(`api.telegram.org`) fallen unter Last mit `[Errno -3] Temporary failure in name
resolution` aus - separater Beobachtungspunkt, nicht Teil dieses Patches.

## Rezept (Neuanwendung nach Image-Update)

1. Helper + `gate:`-Block (unten) in die Zieldatei einsetzen.
   Anker Helper: `        query_user_name = getattr(query.from_user, "first_name", None)`
   -> `src.replace(anker, anker + "\n" + helper, 1)`.
   Anker `gate:`-Zweig: `        # --- Model picker callbacks ---`
   -> `src.replace(anker, gate + "\n" + anker, 1)`.
   Base64-Variante: `docker exec hermes python -c "..."` (Backticks/Quotes meiden),
   danach `python -m py_compile /opt/hermes/plugins/platforms/telegram/adapter.py`.
2. `docker restart hermes` (Adapter reconnectet, getUpdates wieder da - 1-2 min).
3. Pruefen: `grep -c "_archon_req" .../adapter.py` >= 6 und `grep -c "gate:approve"` = 1.
4. Live-Test: Profil + neues Tool speichern -> Gate-Ping -> OK druecken ->
   Toast "Rechte freigegeben" + Profil gespeichert (Log: keine `Gate-Callback ... fehlgeschlagen`).

## Patch-Code

### (a) Helper - einfuegen in `_handle_callback_query` nach `query_user_name = ...`

```python
        async def _archon_req(_method, _url, **_kw):
            """ARCHON-OS-Request mit Retry (3 Versuche, Backoff) + IP-Notfallpfad.

            12.10.2026 (User-Entscheidung, Robustheit): Ein transienter
            Container-DNS-/Connect-Fehler (httpx.ConnectError mit LEERER
            Meldung, im Hochlast-Fenster beobachtet) verschluckte sonst einen
            Owner-Klick. Hostname bleibt erste Wahl; erst wenn er dauerhaft
            scheitert, wird EINMAL gegen die per DNS aufgeloeste IP versucht
            (nicht britt: die IP wird erst im Notfall frisch bestimmt).
            """
            import asyncio as _asyncio
            import httpx as _hx
            _last = None
            for _i in range(3):
                try:
                    async with _hx.AsyncClient(timeout=12.0) as _cl:
                        return await _cl.request(_method, _url, **_kw)
                except Exception as _e:
                    _last = _e
                    logger.warning(
                        "[Telegram] ARCHON-Request %s Versuch %s/3 fehlgeschlagen: %s",
                        _url, _i + 1, str(_e) or type(_e).__name__)
                    if _i < 2:
                        await _asyncio.sleep(0.5 * (_i + 1))
            try:
                import socket as _sock
                from urllib.parse import urlsplit as _us, urlunsplit as _uun
                _u = _us(_url)
                _ip = _sock.gethostbyname(_u.hostname)
                _url2 = _uun((_u.scheme, "%s:%s" % (_ip, _u.port or 80),
                              _u.path, _u.query, _u.fragment))
                logger.warning("[Telegram] ARCHON-Request IP-Notfallpfad -> %s", _url2)
                async with _hx.AsyncClient(timeout=12.0) as _cl:
                    return await _cl.request(_method, _url2, **_kw)
            except Exception:
                raise _last
```

### (b) `gate:`-Zweig - einfuegen VOR `        # --- Model picker callbacks ---`

```python
        if data.startswith("gate:"):
            parts = data.split(":", 2)
            decision = parts[1] if len(parts) > 1 else ""
            gate_id = parts[2] if len(parts) > 2 else ""
            caller_id = str(getattr(query.from_user, "id", ""))
            if not self._is_callback_user_authorized(
                caller_id,
                chat_id=query_chat_id,
                chat_type=str(query_chat_type) if query_chat_type is not None else None,
                thread_id=str(query_thread_id) if query_thread_id is not None else None,
                user_name=query_user_name,
            ):
                await query.answer(text="\u26d4 You are not authorized to decide permission gates.")
                return
            if decision in ("approve", "reject") and gate_id:
                ok = False
                err = None
                try:
                    _resp = await _archon_req(
                        "POST",
                        "http://ARCHON-OS:8501/api/permission-gates/%s/decide" % gate_id,
                        json={"decision": decision},
                    )
                    ok = _resp.status_code == 200
                    if not ok:
                        err = "HTTP %s" % _resp.status_code
                except Exception as _exc:
                    err = str(_exc) or type(_exc).__name__
                    logger.error("[Telegram] Gate-Callback an ARCHON fehlgeschlagen: %s", err)
                if ok and decision == "approve":
                    await query.answer(text="\u2705 Rechte freigegeben - wird jetzt ausgefuehrt.")
                elif ok:
                    await query.answer(text="\u274c Rechte verweigert - nichts wurde geaendert.")
                else:
                    await query.answer(text="\u26a0 Archon nicht erreichbar (%s) - sende Text: 'Erlauben %s'" % (err or "?", gate_id))
            else:
                await query.answer(text="Ungueltige Gate-Daten.")
            return
```

### (c) `app:`-Zweig - die 4 HTTP-Bloecke auf den Helper umstellen

```python
# details, Kanban:
r = await _archon_req("GET", f"{_archon}/api/operations/kanban/tasks/{ref_id}")
# details, Mission-Control-Fallback:
r = await _archon_req("GET", f"{_archon}/api/mission-control/state")
# approve/reject, Kanban:
r = await _archon_req("PATCH", f"{_archon}/api/operations/kanban/tasks/{ref_id}/status",
                      json={"status": kanban_status})
# approve/reject, Mission-Control-Fallback:
r = await _archon_req("POST", f"{_archon}/api/mission-control/tasks/move",
                      json={"task_id": ref_id, "target_status": mission_status})
```
