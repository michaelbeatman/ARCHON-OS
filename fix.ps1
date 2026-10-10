$path = "main.py"
$content = Get-Content $path -Raw
$content = $content.Replace('@app.get("/api/llm-providers/prices")' + "`r`n`r`n" + '_openrouter_price_cache = None', '_openrouter_price_cache = None' + "`r`n`r`n" + '@app.get("/api/llm-providers/prices")')
$content = $content.Replace('@app.get("/api/llm-providers/prices")' + "`n`n" + '_openrouter_price_cache = None', '_openrouter_price_cache = None' + "`n`n" + '@app.get("/api/llm-providers/prices")')
[IO.File]::WriteAllText($path, $content)
