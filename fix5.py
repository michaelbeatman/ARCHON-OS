import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

# We need to find the entire get_llm_prices function and replace it!
start_idx = c.find('def get_llm_prices():')
if start_idx != -1:
    # find next def or end of file
    end_idx = c.find('def ', start_idx + 10)
    if end_idx == -1:
        end_idx = len(c)
    
    old_func = c[start_idx:end_idx]
    
    new_func = """def get_llm_prices():
    global _openrouter_price_cache, _openrouter_price_timestamp
    try:
        now = time.time()
        if _openrouter_price_cache is None or (now - _openrouter_price_timestamp > 3600):
            import urllib.request
            import json
            req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data", [])
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
            return {"status": "ok", "prices": _openrouter_price_cache}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": _openrouter_price_cache or {}}

"""
    c = c[:start_idx] + new_func + c[end_idx:]
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Fixed!")
else:
    print("Function not found!")
