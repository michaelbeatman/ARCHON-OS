import json
import httpx
import asyncio
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "agentic_memory.db")

async def update_prices():
    print("Fetching OpenRouter pricing...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            resp.raise_for_status()
            models_data = resp.json()
            
        prices = {}
        for m in models_data.get("data", []):
            model_id = m["id"]
            pricing = m.get("pricing", {})
            try:
                # OpenRouter gives price per 1 token. Multiply by 1,000,000 for per-1M pricing.
                prompt_1m = float(pricing.get("prompt", 0)) * 1000000
                completion_1m = float(pricing.get("completion", 0)) * 1000000
            except (ValueError, TypeError):
                prompt_1m = 0.0
                completion_1m = 0.0
            
            prices[model_id] = {
                "prompt_1m": prompt_1m,
                "completion_1m": completion_1m,
                "context_length": m.get("context_length", 0)
            }
            
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", 
                         ("openrouter_prices", json.dumps(prices)))
        print(f"Successfully cached prices per 1M tokens for {len(prices)} models.")
    except Exception as e:
        print(f"Failed to fetch prices: {e}")

if __name__ == "__main__":
    asyncio.run(update_prices())
