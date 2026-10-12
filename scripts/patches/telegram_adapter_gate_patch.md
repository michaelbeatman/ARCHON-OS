# Telegram-Adapter-Patch: Permission-Gate-Buttons (12.10.2026)

**Zweck:** Die Inline-Buttons `gate:approve:<gate_id>` / `gate:reject:<gate_id>`
(aus `telegram_notify._create_permission_gate`) direkt im Hermes-Telegram-Adapter
verarbeiten: Owner-Autorisierung, POST an
`http://ARCHON-OS:8501/api/permission-gates/<id>/decide`, sofortige
`query.answer()`-Quittung (✅/❌-Toast unter dem Knopf).

**Datei:** `/opt/hermes/plugins/platforms/telegram/adapter.py`, eingefuegt als
eigener `if data.startswith("gate:"):`-Zweig VOR `# --- Model picker callbacks ---`.

**Warum gesichert:** Der vergleichbare 09.10.-Patch (`app:*`-HITL-Buttons) ist bei
einem Hermes-Image-Update VERSCHWUNDEN (grep findet `app:approve` nirgends mehr) -
genau das Risiko steht auch im Skill archon-remote-control. Nach jedem
Hermes-Image-Update diesen Patch ERNEUT anwenden (Rezept siehe unten).

## Rezept (Neuanwendung)

1. Patch-Code (unten) als base64 kodieren und per `docker exec hermes python -c ...`
   wie folgt einsetzen: anker = `        # --- Model picker callbacks ---`,
   `src.replace(anker, block + anker, 1)`, danach `py_compile`.
2. `docker restart hermes` (Telegram-Adapter reconnectet, getUpdates wieder da).
3. Pruefen: `grep -c "gate:approve" .../adapter.py` muss 1 liefern.
4. Ersten Test: ein neues Gate anlegen (Profil + neues Tool) -> Knopf druecken ->
   Toast "Rechte freigegeben" + Profil gespeichert.

## Patch-Code (Python, 8-space-Eingueckung)

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
                    import httpx as _hx
                    async with _hx.AsyncClient(timeout=12.0) as _cl:
                        _resp = await _cl.post(
                            "http://ARCHON-OS:8501/api/permission-gates/%s/decide" % gate_id,
                            json={"decision": decision},
                        )
                        ok = _resp.status_code == 200
                except Exception as _exc:
                    err = str(_exc)
                    logger.error("[Telegram] Gate-Callback an ARCHON fehlgeschlagen: %s", _exc)
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
