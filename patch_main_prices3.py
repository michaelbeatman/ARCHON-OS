import os

p = '/app/main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

old_func = """def get_llm_prices():
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

new_func = """
_openrouter_price_cache = None
_openrouter_price_timestamp = 0

def get_llm_prices():
    global _openrouter_price_cache, _openrouter_price_timestamp
    try:
        now = time.time()
        if _openrouter_price_cache is None or (now - _openrouter_price_timestamp > 3600):
            import requests
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                formatted = {}
                for m in data:
                    pricing = m.get("pricing", {})
                    prompt_price = float(pricing.get("prompt", 0))
                    completion_price = float(pricing.get("completion", 0))
                    formatted[m["id"]] = {
                        "prompt_1m": prompt_price * 1000000,
                        "completion_1m": completion_price * 1000000
                    }
                _openrouter_price_cache = formatted
                _openrouter_price_timestamp = now
                return {"status": "ok", "prices": formatted}
            else:
                return {"status": "error", "message": "Failed to fetch from openrouter", "prices": _openrouter_price_cache or {}}
        else:
            return {"status": "ok", "prices": _openrouter_price_cache}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": _openrouter_price_cache or {}}"""

c = c.replace(old_func, new_func)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
