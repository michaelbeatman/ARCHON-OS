$path = "main.py"
$content = Get-Content $path -Raw
# Strip out the problematic variables temporarily wherever they are near the decorator
$content = $content -replace '(?s)@app\.get\("/api/llm-providers/prices"\)\s*_openrouter_price_cache = None\s*_openrouter_price_timestamp = 0\s*', ""

# And the other combination if I already replaced part of it
$content = $content -replace '(?s)_openrouter_price_cache = None\s*@app\.get\("/api/llm-providers/prices"\)\s*_openrouter_price_timestamp = 0\s*', ""

# Find where the function is and prepend variables AND decorator
$funcStr = 'def get_llm_prices():'
$replacement = '_openrouter_price_cache = None' + "`n" + '_openrouter_price_timestamp = 0' + "`n`n" + '@app.get("/api/llm-providers/prices")' + "`n" + $funcStr
$content = $content -replace $funcStr, $replacement

[IO.File]::WriteAllText($path, $content)
