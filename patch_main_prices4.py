import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    '@app.get("/api/llm-providers/prices")\n\n_openrouter_price_cache = None',
    '_openrouter_price_cache = None\n\n@app.get("/api/llm-providers/prices")'
)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
