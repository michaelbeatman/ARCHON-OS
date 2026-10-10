$path = "main.py"
$content = Get-Content $path -Raw

# Replace the bare function def with variables and decorator
$content = $content -replace 'def get_llm_prices\(\):', "_openrouter_price_cache = None`n_openrouter_price_timestamp = 0`n`n@app.get('/api/llm-providers/prices')`ndef get_llm_prices():"

[IO.File]::WriteAllText($path, $content)
