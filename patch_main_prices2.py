import os

p = '/app/main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

old_func = """def get_llm_prices():
    try:
        with _get_state_db() as conn:
            cur = conn.execute("SELECT value FROM kv_store WHERE key = 'openrouter_prices'")
            row = cur.fetchone()
            if row and row[0]:
                return {"status": "ok", "prices": json.loads(row[0])}
        return {"status": "ok", "prices": {}}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": {}}"""

new_func = """def get_llm_prices():
    try:
        cache_path = "/opt/data/provider_models_cache.json"
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'openrouter' in data and 'prices' in data['openrouter']:
                    # Reformat prices to match frontend expectation: { "model_id": { "prompt_1m": x, "completion_1m": y } }
                    raw_prices = data['openrouter']['prices']
                    formatted_prices = {}
                    for k, v in raw_prices.items():
                        formatted_prices[k] = {
                            "prompt_1m": v.get("prompt", 0) * 1000000,
                            "completion_1m": v.get("completion", 0) * 1000000
                        }
                    return {"status": "ok", "prices": formatted_prices}
        return {"status": "ok", "prices": {}}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": {}}"""

c = c.replace(old_func, new_func)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
