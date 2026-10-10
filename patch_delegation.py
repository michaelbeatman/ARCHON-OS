import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = '''        # Antwort & Metriken in SQLite verbuchen
        _save_message_to_db(session_id, "assistant", full_assistant_text, completion_tokens)'''

replacement = '''        # Delegation Interceptor
        try:
            import re, asyncio
            # Parse hermes -p commands
            for m in re.finditer(r'hermes\s+-p\s+([a-zA-Z0-9_-]+)\s+chat.*?-q\s+["\'](.*?)(?=["\'](?:\s|$))', full_assistant_text, re.DOTALL):
                tgt_prof = m.group(1)
                tgt_msg = m.group(2)
                tgt_sess = f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{tgt_prof}"
                with _get_state_db() as conn:
                    _ensure_session_exists(conn, tgt_sess, tgt_prof, "auto/best-coding", tgt_msg[:50])
                _save_message_to_db(tgt_sess, "user", tgt_msg)
                
                async def _bg_reply(s_id, prof_id, query):
                    try:
                        tgt_profiles = api_get_hermes_profiles()
                        t_prof = next((p for p in tgt_profiles if p["id"] == prof_id), None)
                        t_sys = t_prof.get("prompt") if t_prof else "You are a helpful assistant."
                        t_model = t_prof.get("model") if t_prof and t_prof.get("model") else "auto/best-coding"
                        t_provider = provider
                        msgs = [{"role": "system", "content": t_sys}, {"role": "user", "content": query}]
                        
                        ans = ""
                        from backend.agent_router import router_instance
                        async for chunk in router_instance.stream_chat_completion(msgs, t_provider, t_model, all_keys):
                            if not chunk.startswith("ERROR: "):
                                ans += chunk
                        if ans:
                            _save_message_to_db(s_id, "assistant", ans)
                    except Exception as e:
                        logger.error(f"Background delegation error: {e}")
                
                asyncio.create_task(_bg_reply(tgt_sess, tgt_prof, tgt_msg))
        except Exception as e:
            logger.error(f"Delegation parsing error: {e}")

        # Antwort & Metriken in SQLite verbuchen
        _save_message_to_db(session_id, "assistant", full_assistant_text, completion_tokens)'''

if target in c:
    c = c.replace(target, replacement)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Delegation interceptor injected!")
else:
    print("Target not found.")
